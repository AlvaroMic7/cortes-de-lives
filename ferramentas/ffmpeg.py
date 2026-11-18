from shutil import which


def achar_ffmpeg(programa="ffmpeg"):
    executavel = which(programa)
    if not executavel:
        raise SystemExit(f"{programa} não encontrado. Instale o FFmpeg e confira se está no PATH.")
    return executavel
