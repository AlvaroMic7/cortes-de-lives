"""Grava e transcreve uma live em andamento em blocos."""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from ffmpeg import achar_ffmpeg  # noqa: E402
from transcrever import SR, ler_wav  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRUTOS = os.path.join(RAIZ, "trabalhos", "gravacoes")
YTDLP = [sys.executable, "-m", "yt_dlp", "--js-runtimes", "node", "--socket-timeout", "20", "-q", "--no-warnings"]


def ler_json(caminho, padrao=None):
    try:
        return json.load(open(caminho, encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def salvar_json(caminho, dados):
    tmp = caminho + ".tmp"
    json.dump(dados, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for tentativa in range(40):  # no Windows, outro processo lendo o arquivo bloqueia a troca por instantes
        try:
            os.replace(tmp, caminho)
            return
        except PermissionError:
            if tentativa == 39:
                raise
            time.sleep(0.05)


def info_live(link):
    """Canal, id e se está ao vivo agora (None se o link não respondeu; {"is_live": False} se o canal está offline)."""
    r = subprocess.run(YTDLP + ["--skip-download", "-J", link], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        return {"is_live": False} if re.search(r"not currently live|is offline|não está ao vivo", r.stderr or "", re.I) else None
    return json.loads(r.stdout)


def urls_fluxo(link, altura):
    """Endereços HLS: um (Twitch, vídeo+áudio juntos) ou dois (YouTube, vídeo e áudio separados)."""
    fmt = f"bv*[height<={altura}][vcodec^=avc]+ba[acodec^=mp4a]/b[height<={altura}][vcodec^=avc]/b[height<={altura}]/b"
    r = subprocess.run(YTDLP + ["-g", "-f", fmt, link], capture_output=True, text=True, encoding="utf-8")
    return [u for u in r.stdout.split() if u.startswith("http")]


def duracao(arquivo):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arquivo], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


class Live:
    def __init__(self, args):
        self.link = args.link
        self.bloco = args.bloco
        self.modelo_nome = args.modelo
        self.threads = args.threads
        self.vocabulario = args.vocabulario
        self.altura = args.altura
        self.max_s = args.max_horas * 3600
        self.espera = args.espera
        self.modelo = None
        self.ffmpeg = None
        self.sessao = 0
        self.inicio = time.time()

        link = self.link
        info = info_live(link)
        if info is None:
            sys.exit("Não consegui consultar a live. Confira o link e a conexão.")
        if not info.get("is_live"):
            sys.exit(f"{link} não está ao vivo agora.")
        canal_id = re.sub(r"[^a-z0-9]", "", (info.get("uploader_id") or info.get("channel") or "canal").lower())
        # YouTube: usa o link da live em si (o /@canal/live pode apontar para outra depois)
        if info.get("extractor_key", "").startswith("Youtube"):
            self.link = info.get("webpage_url") or link
        # Uma nova gravação da mesma live recebe sua própria pasta.
        id_live = re.sub(r"[^a-zA-Z0-9_-]", "-", str(info["id"]))
        base, n = os.path.join(BRUTOS, f"{canal_id or 'canal'}-{id_live}"), 1
        self.pasta = base
        while os.path.exists(os.path.join(self.pasta, "video.mp4")):
            n += 1
            self.pasta = f"{base}-{n}"
        self.vivo = os.path.join(self.pasta, "ao-vivo")
        self.partes = os.path.join(self.pasta, "partes")
        os.makedirs(self.vivo, exist_ok=True)
        os.makedirs(self.partes, exist_ok=True)
        self.indice_arq = os.path.join(self.vivo, "indice.json")
        self.indice = ler_json(self.indice_arq, [])
        sessoes = [int(m.group(1)) for f in os.listdir(self.vivo) if (m := re.match(r"s(\d+)\.csv$", f))]
        self.sessao = max(sessoes, default=0)
        estado = ler_json(os.path.join(self.pasta, "live.json"), {})
        self.estado = {**estado, "canal": info.get("uploader") or info.get("channel"), "url": self.link, "origem": link, "pid": os.getpid(),
                       "plataforma": next((n for n in ("Twitch", "Kick") if n.lower() in info.get("extractor_key", "").lower()), "YouTube"),
                       "titulo": info.get("title"), "data": estado.get("data") or datetime.now().strftime("%Y-%m-%d"),
                       "comeco": estado.get("comeco") or datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.log(f"pasta {os.path.relpath(self.pasta, RAIZ)} — {self.estado['canal']}: {self.estado['titulo']}")

    # ---------- registro ----------
    def log(self, msg):
        linha = f"[{datetime.now():%H:%M:%S}] {msg}"
        print(linha, flush=True)
        with open(os.path.join(self.pasta, "live.log") if hasattr(self, "pasta") else os.devnull, "a", encoding="utf-8") as f:
            f.write(linha + "\n")

    def salvar_estado(self, situacao, fila=0):
        gravado = sum(p["dur"] for p in self.indice)
        self.estado.update({"situacao": situacao, "minutos_gravados": round(gravado / 60, 1), "pedacos": len(self.indice),
                            "transcritos": sum(1 for p in self.indice if os.path.exists(self.parte_json(p))), "na_fila": fila,
                            "atualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        salvar_json(os.path.join(self.pasta, "live.json"), self.estado)

    # ---------- gravação ----------
    def gravar(self):
        self.streamlink = None
        if "twitch.tv" in self.link:
            self.sessao += 1
            alturas = sorted({1080, 936, 900, 720, 480, 360, self.altura}, reverse=True)
            qualidades = [q for h in alturas if h <= self.altura for q in (f"{h}p60", f"{h}p")]
            with open(os.path.join(self.pasta, "streamlink.log"), "a", encoding="utf-8") as log:
                self.streamlink = subprocess.Popen(
                    [sys.executable, "-m", "streamlink", "--stdout", self.link, ",".join([*qualidades, "best"])],
                    stdout=subprocess.PIPE, stderr=log,
                )
            ent, urls = ["-i", "pipe:0"], ["pipe"]
        else:
            urls = urls_fluxo(self.link, self.altura)
            if not urls:
                return False
            self.sessao += 1
            ent = []
            for u in urls:
                ent += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10", "-i", u]
        s = f"s{self.sessao}"
        cmd = [FFMPEG, "-v", "error", "-y", *ent, "-map", "0:v:0", "-map", f"{len(urls) - 1}:a:0", "-c", "copy",
               "-f", "segment", "-segment_time", str(self.bloco), "-reset_timestamps", "1",
               "-segment_list", os.path.join(self.vivo, f"{s}.csv"), "-segment_list_type", "csv",
               os.path.join(self.vivo, f"{s}-%04d.ts")]
        self.inicio_sessao, self._tam, self._tam_em, self._pedaco, self._pedaco_em = time.time(), None, time.time(), None, time.time()
        with open(os.path.join(self.pasta, "ffmpeg.log"), "a", encoding="utf-8") as log:
            self.ffmpeg = subprocess.Popen(cmd, stdin=self.streamlink.stdout if self.streamlink else subprocess.PIPE, stderr=log)
        if self.streamlink:
            self.streamlink.stdout.close()
        self.log(f"gravando (sessão {self.sessao}, {len(urls)} fluxo{'s' if len(urls) > 1 else ''}, pedaços de {self.bloco} s)")
        return True

    def gravacao_travada(self):
        """Pedaço atual sem crescer há 90 s (ffmpeg preso, comum depois do anúncio da Twitch) ou longo demais
        (pedaço de 17 min visto em 18/11: transcrição atrasa e o corte demora)."""
        atuais = sorted(f for f in os.listdir(self.vivo) if f.startswith(f"s{self.sessao}-") and f.endswith(".ts"))
        if not atuais:
            return "sem arquivo" if time.time() - self.inicio_sessao > 90 else None
        arq = os.path.join(self.vivo, atuais[-1])
        tam = os.path.getsize(arq)
        if tam != getattr(self, "_tam", None):
            self._tam, self._tam_em = tam, time.time()
        if time.time() - self._tam_em > 90:
            return "arquivo parado"
        if self._pedaco != atuais[-1]:
            self._pedaco, self._pedaco_em = atuais[-1], time.time()
        if time.time() - self._pedaco_em > self.bloco * 2.5:
            return "pedaço longo demais"
        return None

    def parar_gravacao(self):
        if getattr(self, "streamlink", None) and self.streamlink.poll() is None:
            self.streamlink.kill()  # o ffmpeg recebe o fim da entrada e fecha o último pedaço sozinho
            try:
                self.ffmpeg.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        if self.ffmpeg and self.ffmpeg.poll() is None:
            try:
                self.ffmpeg.stdin.write(b"q")
                self.ffmpeg.stdin.flush()
                self.ffmpeg.wait(timeout=30)
            except (AttributeError, OSError, subprocess.TimeoutExpired):
                self.ffmpeg.kill()
                self.ffmpeg.wait()

    def fechados(self, tudo=False):
        """Pedaços prontos na ordem: os listados no CSV de cada sessão (o ffmpeg só lista quando fecha).
        Com tudo=True (ffmpeg parado) entram também os que ficaram fora da lista."""
        lista = []
        for n in range(1, self.sessao + 1):
            arquivo = os.path.join(self.vivo, f"s{n}.csv")
            nomes = []
            if os.path.exists(arquivo):
                with open(arquivo, encoding="utf-8", newline="") as indice:
                    nomes = [linha[0] for linha in csv.reader(indice) if len(linha) == 3]
            if tudo:
                soltos = sorted(f for f in os.listdir(self.vivo) if f.startswith(f"s{n}-") and f.endswith(".ts"))
                nomes += [f for f in soltos if f not in nomes]
            lista += nomes
        return lista

    def atualizar_indice(self, tudo=False):
        ja = {p["arquivo"] for p in self.indice}
        fim = sum(p["dur"] for p in self.indice)
        novos = 0
        for nome in self.fechados(tudo):
            if nome in ja:
                continue
            d = duracao(os.path.join(self.vivo, nome))
            if d < 0.5:
                continue
            self.indice.append({"arquivo": nome, "ini": round(fim, 3), "dur": round(d, 3)})
            fim += d
            novos += 1
        if novos:
            salvar_json(self.indice_arq, self.indice)
        return novos

    # ---------- transcrição ----------
    def parte_json(self, p):
        return os.path.join(self.partes, p["arquivo"].replace(".ts", ".json"))

    def transcrever(self, p):
        from faster_whisper import WhisperModel

        if self.modelo is None:
            self.modelo = WhisperModel(self.modelo_nome, device="cpu", compute_type="int8", cpu_threads=self.threads)
        wav = os.path.join(self.vivo, "tmp16k.wav")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", os.path.join(self.vivo, p["arquivo"]), "-af", "aresample=async=1:first_pts=0", "-ac", "1", "-ar", str(SR), wav], check=True)
        t0 = time.time()
        segs, _ = self.modelo.transcribe(ler_wav(wav), language="pt", word_timestamps=True, vad_filter=True, initial_prompt=self.vocabulario)
        palavras, frases = [], []
        for s in segs:
            if s.start >= p["dur"]:
                continue
            frases.append({"ini": round(p["ini"] + s.start, 2), "fim": round(p["ini"] + s.end, 2), "texto": s.text.strip()})
            for w in s.words or []:
                palavras.append({"t": w.word.strip(), "ini": round(p["ini"] + w.start, 2), "fim": round(p["ini"] + w.end, 2)})
        os.remove(wav)
        salvar_json(self.parte_json(p), {"palavras": palavras, "frases": frases})
        self.log(f"{p['arquivo']} transcrito ({p['ini'] / 60:.0f}-{(p['ini'] + p['dur']) / 60:.0f} min, {len(frases)} frases, {time.time() - t0:.0f} s)")

    def juntar_transcricao(self):
        palavras, frases, fim = [], [], 0.0
        for p in self.indice:
            d = ler_json(self.parte_json(p))
            if d is None:
                break  # para no primeiro buraco: a transcrição só cresce em ordem
            palavras += d["palavras"]
            frases += d["frases"]
            fim = p["ini"] + p["dur"]
        salvar_json(os.path.join(self.pasta, "transcricao.json"), {"duracao": round(fim, 2), "ao_vivo": True, "palavras": palavras, "frases": frases})
        with open(os.path.join(self.pasta, "transcricao.txt"), "w", encoding="utf-8") as f:
            for fr in frases:
                f.write(f"[{fr['ini']:7.2f} - {fr['fim']:7.2f}] {fr['texto']}\n")

    def transcrever_pendentes(self, um=False):
        feitos = 0
        for p in self.indice:
            if not os.path.exists(self.parte_json(p)):
                self.transcrever(p)
                feitos += 1
                self.juntar_transcricao()
                if um:
                    break
        return feitos

    # ---------- fim ----------
    def finalizar(self):
        self.parar_gravacao()
        self.atualizar_indice(tudo=True)
        self.salvar_estado("transcrevendo o resto")
        self.transcrever_pendentes()
        self.juntar_transcricao()
        if not self.indice:
            self.salvar_estado("encerrada")
            self.log("nada gravado")
            return
        lista = os.path.join(self.vivo, "lista.txt")
        with open(lista, "w", encoding="utf-8") as f:
            for p in self.indice:
                f.write(f"file '{p['arquivo']}'\n")
        video = os.path.join(self.pasta, "video.mp4")
        parcial = os.path.join(self.pasta, "video.parcial.mp4")
        self.log("juntando os pedaços em video.mp4")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", "-bsf:a", "aac_adtstoasc",
                        "-movflags", "+faststart", parcial], check=True)
        os.replace(parcial, video)
        total = sum(p["dur"] for p in self.indice)
        d = duracao(video)
        tr = ler_json(os.path.join(self.pasta, "transcricao.json"))
        tr.pop("ao_vivo", None)
        salvar_json(os.path.join(self.pasta, "transcricao.json"), tr)
        self.salvar_estado("encerrada")
        if abs(d - total) < 2:
            for f in os.listdir(self.vivo):
                os.remove(os.path.join(self.vivo, f))
            os.rmdir(self.vivo)
            for f in os.listdir(self.partes):
                os.remove(os.path.join(self.partes, f))
            os.rmdir(self.partes)
        else:
            self.log(f"video.mp4 tem {d:.0f} s e os pedaços somam {total:.0f} s: ao-vivo/ mantida para conferir")
        self.log(f"encerrada: {total / 60:.0f} min gravados -> {os.path.relpath(video, RAIZ)}")

    def rodar(self):
        parar = os.path.join(self.pasta, "PARAR")
        if os.path.exists(parar):
            os.remove(parar)
        if not self.gravar():
            sys.exit("não consegui o endereço do fluxo")
        queda = None
        try:
            while True:
                self.atualizar_indice()
                fila = sum(1 for p in self.indice if not os.path.exists(self.parte_json(p)))
                self.salvar_estado("gravando" if self.ffmpeg.poll() is None else "reconectando", fila)
                if os.path.exists(parar):
                    self.log("PARAR encontrado")
                    break
                if time.time() - self.inicio > self.max_s:
                    self.log("limite de horas atingido")
                    break
                if self.ffmpeg.poll() is not None:  # fluxo caiu: tenta voltar até --espera
                    if getattr(self, "streamlink", None) and self.streamlink.poll() is None:
                        self.streamlink.kill()
                    self.atualizar_indice(tudo=True)
                    queda = queda or time.time()
                    info = info_live(self.link)
                    if info and info.get("is_live") and self.gravar():
                        self.log("reconectado")
                        queda = None
                        continue
                    if info is None:  # sem resposta (internet caiu): não conta como "a live acabou"
                        self.confirmou_fim = 0
                    elif not info.get("is_live"):
                        self.confirmou_fim = getattr(self, "confirmou_fim", 0) + 1
                    if time.time() - queda > self.espera and getattr(self, "confirmou_fim", 0) >= 3:
                        self.log("a live acabou")
                        break
                    time.sleep(15)
                    continue
                travado = self.gravacao_travada()
                if travado:
                    self.log(f"gravação travada ({travado}): reiniciando o ffmpeg")
                    if self.streamlink:
                        self.streamlink.kill()
                    self.ffmpeg.kill()
                    self.ffmpeg.wait()
                    continue
                if not self.transcrever_pendentes(um=True):
                    time.sleep(10)
        except KeyboardInterrupt:
            self.log("interrompido (Ctrl+C)")
        finally:
            self.finalizar()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("link", help="endereço da live na Twitch, no YouTube ou na Kick")
    parser.add_argument("--bloco", type=int, default=300, help="duração aproximada de cada bloco, em segundos")
    parser.add_argument("--modelo", default="small", help="modelo do Whisper (ex.: base, small, medium)")
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) // 2), help="threads de CPU para a transcrição")
    parser.add_argument("--vocabulario", help="nomes e termos para orientar a transcrição")
    parser.add_argument("--altura", type=int, default=1080, help="altura desejada do vídeo de origem")
    parser.add_argument("--max-horas", type=float, default=8, help="limite de horas de gravação")
    parser.add_argument("--espera", type=int, default=600, help="segundos de espera antes de confirmar que a live acabou")
    args = parser.parse_args()
    if min(args.bloco, args.threads, args.altura, args.max_horas) <= 0 or args.espera < 0:
        parser.error("bloco, threads, altura e max-horas devem ser positivos. Espera deve ser igual ou maior que zero.")

    global FFMPEG, FFPROBE
    FFMPEG = achar_ffmpeg()
    FFPROBE = achar_ffmpeg("ffprobe")
    Live(args).rodar()


if __name__ == "__main__":
    main()
