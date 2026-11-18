"""Prepara os trechos selecionados e suas legendas para exportação vertical."""
import argparse
import json
import math
import re
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from ffmpeg import achar_ffmpeg  # noqa: E402

FPS = 30
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANO_MAX = 3.0  # s: plano de rosto mais longo que isso é quebrado (troca de zoom) para dar ritmo

LAYOUTS = {"cam", "largo", "jogo", "comp", "split", "tela"}


def layout_em(layouts, t):
    atual = layouts[0][1]
    for ini, nome in layouts:
        if t >= ini:
            atual = nome
    return atual


def entrada(bruto, ini, fim, pasta):
    """Argumentos de entrada do ffmpeg a partir do segundo ini: video.mp4 ou, com a live ainda
    em gravação (ferramentas/live.py), só os pedaços de ao-vivo/ que cobrem [ini, fim]."""
    video = os.path.join(bruto, "video.mp4")
    if os.path.exists(video):
        return ["-ss", f"{ini:.3f}", "-i", video]
    indice = json.load(open(os.path.join(bruto, "ao-vivo", "indice.json"), encoding="utf-8"))
    usados = [p for p in indice if p["ini"] + p["dur"] > ini and p["ini"] < fim]
    if not usados or usados[-1]["ini"] + usados[-1]["dur"] < fim - 0.1:
        raise RuntimeError(f"o trecho {ini:.0f}-{fim:.0f} s ainda não foi gravado por inteiro")
    lista = os.path.join(pasta, "pedacos.txt")
    with open(lista, "w", encoding="utf-8") as f:
        for p in usados:
            caminho = Path(bruto, "ao-vivo", p["arquivo"]).resolve().as_posix()
            caminho = caminho.replace("'", "'\\''")
            f.write(f"file '{caminho}'\n")
    return ["-ss", f"{ini - usados[0]['ini']:.3f}", "-f", "concat", "-safe", "0", "-i", lista]


PAUSAS = {"cam": (0.45, 0.1), "largo": (0.45, 0.1), "split": (1.2, 0.35), "tela": (1.2, 0.35)}  # (pausa máxima, sobra) por layout; demais: (2.5, 0.9)


def picos_de_voz(fonte, ini_fonte, mapa):
    """Momentos de voz bem mais alta que o normal do trecho (grito, risada), já no tempo novo, em quadros."""
    r = subprocess.run([achar_ffmpeg(), "-v", "error", "-i", fonte, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    jan = 800  # 0,1 s
    n = len(a) // jan
    if n < 20:
        return []
    db = 20 * np.log10(np.sqrt((a[: n * jan].reshape(n, jan) ** 2).mean(axis=1)) + 1e-6)
    falando = db[db > np.percentile(db, 30)]
    if not len(falando):
        return []
    limite = max(np.median(falando) + 2.2 * falando.std(), -18)
    picos, ult = [], -99
    for i in range(1, n - 1):
        if db[i] >= limite and db[i] >= db[i - 1] and db[i] >= db[i + 1] and i / 10 - ult >= 3:
            t = ini_fonte + i / 10
            for a0, b0, novo in mapa:
                if a0 <= t <= b0:
                    picos.append(round((novo + t - a0) * FPS))
                    ult = i / 10
                    break
    return picos


def montar(bruto, dados, tr, corte):
    """Cria a pasta do corte e devolve o caminho dela."""
    palavras = tr["palavras"]
    dados = {**dados, "layouts": corte.get("layouts") or dados["layouts"], "regioes": {**dados.get("regioes", {}), **(corte.get("regioes") or {})}}
    layouts = dados["layouts"]
    viradas = [l[0] for l in layouts]
    # 1. intervalos mantidos do original
    manter = []  # [ini, fim, layout]
    for ini, fim in corte["trechos"]:
        ws = [w for w in palavras if w["ini"] >= ini - 0.05 and w["fim"] <= fim + 0.3]
        a = max(ini - 0.08, 0)
        for w1, w2 in zip(ws, ws[1:]):
            lay = layout_em(layouts, w1["fim"])
            gap = w2["ini"] - w1["fim"]
            limite, sobra = PAUSAS.get(lay, (2.5, 0.9))
            if gap > limite:
                manter.append([a, w1["fim"] + sobra])
                a = w2["ini"] - sobra
        manter.append([a, min(fim + 0.25, tr["duracao"])])
    # 2. quebra nas trocas de layout e em planos longos de rosto
    planos = []
    for a, b in manter:
        cortes_t = [a] + [v for v in viradas if a < v < b] + [b]
        for x, y in zip(cortes_t, cortes_t[1:]):
            lay = layout_em(layouts, x + 0.01)
            if lay == "cam" and y - x > PLANO_MAX * 1.4:
                # quebra em início de palavra, perto de cada PLANO_MAX
                marcos, ult = [x], x
                for w in palavras:
                    if x < w["ini"] < y - 1.2 and w["ini"] - ult >= PLANO_MAX:
                        marcos.append(w["ini"] - 0.04)
                        ult = w["ini"]
                marcos.append(y)
                planos += [[m1, m2, lay] for m1, m2 in zip(marcos, marcos[1:])]
            else:
                planos.append([x, y, lay])
    # 3. linha do tempo nova, em quadros
    ini_fonte = max(min(p[0] for p in planos) - 1, 0)
    fim_fonte = min(max(p[1] for p in planos) + 1, tr["duracao"])
    saida, mapa, quadro, zoom = [], [], 0, False
    for k, (a, b, lay) in enumerate(planos):
        dur = max(1, round((b - a) * FPS))
        continua = k > 0 and abs(planos[k - 1][1] - a) < 0.02 and planos[k - 1][2] == lay
        if lay == "cam":
            zoom = not zoom
        saida.append({"de": quadro, "dur": dur, "fonte": round((a - ini_fonte) * FPS), "layout": lay, "zoom": zoom if lay == "cam" else False, "salto": not continua and k > 0})
        mapa.append((a, b, quadro / FPS))
        quadro += dur
    total = quadro / FPS

    def novo_tempo(t):
        for a, b, n in mapa:
            if a - 0.02 <= t <= b + 0.02:
                return round(n + min(max(t - a, 0), b - a), 2)
        return None

    leg = []
    for w in palavras:
        i, f = novo_tempo(w["ini"]), novo_tempo(w["fim"])
        if i is not None and f is not None and f > i:
            leg.append({"t": w["t"], "ini": i, "fim": f, "cena": "corte"})

    pasta = os.path.join(RAIZ, "trabalhos", "cortes", f"{dados['data']}-corte-{corte['slug']}")
    os.makedirs(pasta, exist_ok=True)
    subprocess.run([achar_ffmpeg(), "-v", "error", "-y", *entrada(bruto, ini_fonte, fim_fonte, pasta), "-t", f"{fim_fonte - ini_fonte:.3f}",
                    "-r", str(FPS), "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-g", "15", "-pix_fmt", "yuv420p", "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-b:a", "192k", os.path.join(pasta, "fonte.mp4")], check=True)
    host = (urlparse(dados["url"]).hostname or "").lower()
    plataformas = {"twitch.tv": "Twitch", "kick.com": "Kick", "youtube.com": "YouTube", "youtu.be": "YouTube"}
    plataforma = dados.get("plataforma") or next(
        (nome for dominio, nome in plataformas.items() if host == dominio or host.endswith("." + dominio)),
        "Arquivo local",
    )
    enfase = picos_de_voz(os.path.join(pasta, "fonte.mp4"), ini_fonte, mapa)
    json.dump({"titulo": corte["titulo"], "canal": dados["canal"], "url": dados["url"], "plataforma": plataforma, "selo": corte.get("selo", dados.get("selo")),
               "rotulos": corte.get("rotulos"), "regioes": dados["regioes"], "enfase": enfase, "planos": saida},
              open(os.path.join(pasta, "corte.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"duracao": round(total, 2), "palavras": leg, "cenas": [{"id": "corte", "titulo": corte["titulo"], "ini": 0, "fim": round(total, 2)}]},
              open(os.path.join(pasta, "sinc.json"), "w", encoding="utf-8"), ensure_ascii=False)
    if os.path.exists(os.path.join(pasta, "pedacos.txt")):
        os.remove(os.path.join(pasta, "pedacos.txt"))
    bruto_s = sum(b - a for a, b in corte["trechos"])
    print(f"{corte['slug']}: {total:.1f} s ({bruto_s:.1f} s no original, {len(saida)} planos, {len(enfase)} ênfases) -> {os.path.relpath(pasta, RAIZ)}")
    return pasta


def ler_json(caminho):
    with open(caminho, encoding="utf-8-sig") as arquivo:
        return json.load(arquivo)


def numero(valor):
    return type(valor) in (float, int) and math.isfinite(valor)


def validar_layouts(layouts):
    anterior = -1
    for marco in layouts:
        if not isinstance(marco, list) or len(marco) != 2:
            raise ValueError("Cada marco de layout deve ser [segundo, nome].")
        segundo, nome = marco
        if not numero(segundo) or segundo < 0 or segundo <= anterior or nome not in LAYOUTS:
            raise ValueError("Informe tempos crescentes e um layout válido: " + ", ".join(sorted(LAYOUTS)))
        anterior = segundo
    if not layouts or layouts[0][0] != 0:
        raise ValueError("A lista de layouts deve começar no segundo 0.")


def validar_corte(corte, dados, duracao):
    slug = corte["slug"]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("Use letras minúsculas, números ou hífens no slug.")
    if not corte["titulo"].strip():
        raise ValueError(f"{slug}: informe um título.")
    if not corte["trechos"]:
        raise ValueError(f"{slug}: informe ao menos um trecho.")
    anterior = 0
    for ini, fim in corte["trechos"]:
        if not (numero(ini) and numero(fim) and anterior <= ini < fim <= duracao):
            raise ValueError(f"{slug}: informe trechos válidos, em ordem e até {duracao:.2f} s de transcrição disponível.")
        anterior = fim
    validar_layouts(corte.get("layouts") or dados["layouts"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bruto", help="pasta da gravação com transcricao.json")
    parser.add_argument("config", help="arquivo JSON com os trechos")
    parser.add_argument("slug", nargs="?", help="monta somente este corte")
    args = parser.parse_args()

    try:
        dados = ler_json(args.config)
        dados.setdefault("layouts", [[0, "tela"]])
        dados.setdefault("url", "")
        dados.setdefault("data", date.today().isoformat())
        if date.fromisoformat(dados["data"]).isoformat() != dados["data"]:
            raise ValueError("Use o formato AAAA-MM-DD em data.")
        if not dados["canal"].strip():
            raise ValueError("Informe o nome do canal.")
        tr = ler_json(Path(args.bruto) / "transcricao.json")
        cortes = [c for c in dados["cortes"] if not args.slug or c["slug"] == args.slug]
        if not cortes:
            raise ValueError("Nenhum corte encontrado para o slug informado." if args.slug else "A lista de cortes está vazia.")
        vistos = set()
        for corte in cortes:
            validar_corte(corte, dados, tr["duracao"])
            if corte["slug"] in vistos:
                raise ValueError(f"Slug repetido: {corte['slug']}")
            vistos.add(corte["slug"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as erro:
        parser.error(str(erro))

    for corte in cortes:
        montar(args.bruto, dados, tr, corte)


if __name__ == "__main__":
    main()
