"""Transcreve um vídeo longo palavra por palavra (para escolher cortes).

Uso:  python ferramentas/transcrever.py <pasta-do-bruto> [--modelo small] [--processos 1]

Lê  <pasta>/video.mp4
Gera <pasta>/transcricao.json  {duracao, palavras:[{t, ini, fim}], frases:[{ini, fim, texto}]}
     <pasta>/transcricao.txt   uma frase por linha com o tempo, para leitura

Trabalha em blocos de ~10 min cortados num silêncio e salva cada bloco em <pasta>/partes/
assim que termina. Se o processo cair (bateria, limite de tempo), rodar o mesmo comando de
novo continua do bloco que faltava. Vários blocos rodam em paralelo (--processos).
"""
import argparse
import json
import os
import subprocess
import sys
import warnings
import wave
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from ffmpeg import achar_ffmpeg  # noqa: E402

SR = 16000
BLOCO = 600  # segundos
BUSCA = 20  # procura o silêncio até 20 s antes/depois do ponto de corte


def ler_wav(wav):
    with wave.open(wav) as w:  # lê o WAV direto (evita o decodificador do faster-whisper, que quebra com a versão do PyAV instalada)
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def limites(audio):
    """Pontos de corte perto de cada múltiplo de BLOCO, no trecho de 0,1 s mais silencioso."""
    total = len(audio) / SR
    jan = SR // 10
    pts = [0.0]
    alvo = BLOCO
    while alvo < total - BLOCO / 3:
        a, b = int((alvo - BUSCA) * SR), int(min(alvo + BUSCA, total) * SR)
        trecho = audio[a:b]
        n = len(trecho) // jan
        energia = np.sqrt((trecho[: n * jan].reshape(n, jan) ** 2).mean(axis=1))
        pts.append(round(a / SR + (int(energia.argmin()) + 0.5) * jan / SR, 2))
        alvo = pts[-1] + BLOCO
    pts.append(round(total, 2))
    return list(zip(pts[:-1], pts[1:]))


def transcrever_bloco(wav, ini, fim, saida, modelo, threads):
    from faster_whisper import WhisperModel

    m = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=threads)
    audio = ler_wav(wav)[int(ini * SR) : int(fim * SR)]
    segs, _ = m.transcribe(audio, language="pt", word_timestamps=True, vad_filter=True)
    palavras, frases = [], []
    for s in segs:
        frases.append({"ini": round(ini + s.start, 2), "fim": round(ini + s.end, 2), "texto": s.text.strip()})
        for w in s.words or []:
            palavras.append({"t": w.word.strip(), "ini": round(ini + w.start, 2), "fim": round(ini + w.end, 2)})
    tmp = saida + ".tmp"
    json.dump({"ini": ini, "fim": fim, "palavras": palavras, "frases": frases}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, saida)
    return saida


def main():
    parser = argparse.ArgumentParser(description="Transcreve o áudio de video.mp4 em português.")
    parser.add_argument("pasta", help="pasta que contém o arquivo video.mp4")
    parser.add_argument("--modelo", default="small", help="modelo do Whisper (ex.: base, small, medium)")
    parser.add_argument("--processos", type=int, default=1, help="número de blocos a transcrever em paralelo")
    args = parser.parse_args()
    pasta, modelo, procs = args.pasta, args.modelo, args.processos
    if procs < 1:
        parser.error("--processos deve ser maior ou igual a 1.")
    video = os.path.join(pasta, "video.mp4")
    if not os.path.isfile(video):
        parser.error(f"Arquivo não encontrado: {video}")
    wav = os.path.join(pasta, "audio16k.wav")
    if not os.path.exists(wav):
        subprocess.run([achar_ffmpeg(), "-v", "error", "-y", "-i", video, "-ac", "1", "-ar", str(SR), wav], check=True)
    partes = os.path.join(pasta, "partes")
    os.makedirs(partes, exist_ok=True)

    mapa = os.path.join(partes, "blocos.json")
    if os.path.exists(mapa):  # mantém os mesmos cortes entre retomadas
        blocos = [tuple(b) for b in json.load(open(mapa, encoding="utf-8"))]
    else:
        blocos = limites(ler_wav(wav))
        json.dump(blocos, open(mapa, "w", encoding="utf-8"))
    arquivos = [os.path.join(partes, f"{i:03d}.json") for i in range(len(blocos))]
    faltam = [i for i, a in enumerate(arquivos) if not os.path.exists(a)]
    print(f"{len(blocos)} blocos, {len(blocos) - len(faltam)} prontos, {len(faltam)} faltando", flush=True)

    threads = max(1, (os.cpu_count() or 4) // procs)
    with ProcessPoolExecutor(max_workers=procs) as ex:
        futs = {ex.submit(transcrever_bloco, wav, *blocos[i], arquivos[i], modelo, threads): i for i in faltam}
        for k, f in enumerate(as_completed(futs), 1):
            f.result()
            i = futs[f]
            print(f"bloco {i} pronto ({blocos[i][0]:.0f}-{blocos[i][1]:.0f}s) — {k}/{len(faltam)}", flush=True)

    palavras, frases = [], []
    for a in arquivos:
        d = json.load(open(a, encoding="utf-8"))
        palavras += d["palavras"]
        frases += d["frases"]
    duracao = blocos[-1][1]
    json.dump({"duracao": duracao, "palavras": palavras, "frases": frases}, open(os.path.join(pasta, "transcricao.json"), "w", encoding="utf-8"), ensure_ascii=False)
    with open(os.path.join(pasta, "transcricao.txt"), "w", encoding="utf-8") as f:
        for fr in frases:
            f.write(f"[{fr['ini']:7.2f} - {fr['fim']:7.2f}] {fr['texto']}\n")
    os.remove(wav)
    for a in arquivos + [mapa]:
        os.remove(a)
    os.rmdir(partes)
    print(f"Gerado: {pasta}/transcricao.json ({len(palavras)} palavras, {len(frases)} frases)")


if __name__ == "__main__":
    main()
