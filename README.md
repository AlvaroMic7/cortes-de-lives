# Cortes de Lives

Transforme uma gravação de live em cortes verticais com título, crédito do canal e legendas em português. Você escolhe os trechos em segundos. A ferramenta transcreve o áudio, ajusta as pausas de acordo com o enquadramento e exporta um MP4 em 9:16, pronto para conferir e editar ou publicar.

Você pode usar um MP4 local, baixar uma gravação com o yt-dlp ou gravar uma transmissão em andamento. Todo o processamento roda no seu computador, sem chave de API. Use gravações próprias ou conteúdo que você tem permissão para gravar e publicar.

## Instalação

Instale [Git](https://git-scm.com/install/), [Python 3.12](https://www.python.org/downloads/), [Node.js 22 ou superior](https://nodejs.org/pt-br/download) e [FFmpeg](https://ffmpeg.org/download.html) com `ffmpeg` e `ffprobe` no PATH. No Windows, você pode instalar o FFmpeg com `winget install --id Gyan.FFmpeg -e` e reabrir o terminal. No macOS com Homebrew, use `brew install ffmpeg`.

Confirme que o terminal encontra os programas.

```text
python --version
node --version
ffmpeg -version
ffprobe -version
```

Clone o projeto e entre na pasta.

```sh
git clone https://github.com/AlvaroMic7/cortes-de-lives.git
cd cortes-de-lives
```

No Windows, use PowerShell.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm ci
```

No macOS ou Linux, use `python3.12 -m venv .venv` e `source .venv/bin/activate` para criar e ativar o ambiente. Rode os mesmos comandos de instalação em seguida. Se o Chromium precisar de bibliotecas adicionais no Linux, consulte o [guia do Remotion](https://www.remotion.dev/docs/chromium-dependencies).

Se o terminal só reconhecer `py` no Windows ou `python3` no macOS/Linux antes da ativação, confira a versão com esse comando.

Na primeira transcrição, o Faster Whisper baixa o modelo escolhido. Na primeira exportação, o Remotion pode baixar o navegador de renderização. Deixe a internet conectada nessas duas etapas. Se o PowerShell impedir a ativação da venv, rode os comandos Python usando `.\.venv\Scripts\python.exe` no lugar de `python` e use `npm.cmd ci` se necessário.

## Primeiro corte com um MP4

### 1. Coloque a gravação na pasta de trabalho

Crie `trabalhos/gravacoes/minha-live/` e salve nela um MP4 com áudio chamado `video.mp4`. Para seguir o exemplo sem mudar os tempos, use uma gravação com pelo menos dez segundos.

Se a gravação estiver em uma plataforma compatível com o yt-dlp, você também pode baixar o VOD direto para essa pasta. Substitua `URL_DA_GRAVACAO` pelo link.

```sh
python -m yt_dlp --js-runtimes node --no-playlist -f "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b" --merge-output-format mp4 --remux-video mp4 -o "trabalhos/gravacoes/minha-live/video.%(ext)s" "URL_DA_GRAVACAO"
```

### 2. Transcreva o vídeo

```sh
python ferramentas/transcrever.py trabalhos/gravacoes/minha-live
```

Leia `transcricao.txt` na pasta da gravação. Os tempos entre colchetes estão em segundos. O `transcricao.json` guarda os tempos de cada palavra usados nas legendas. Para corrigir um nome ou uma palavra, edite o campo `t` da palavra no JSON e mantenha os tempos.

### 3. Escolha os trechos e exporte

Abra [exemplos/cortes.json](exemplos/cortes.json). O exemplo seleciona do segundo 2 ao 10. Ajuste o título, o canal e os tempos para a sua gravação. Use ponto para segundos com decimais, como `12.5`.

```json
{
  "data": "2026-11-18",
  "canal": "Meu canal",
  "layouts": [[0, "tela"]],
  "cortes": [
    {
      "slug": "melhor-momento",
      "titulo": "O melhor momento da live",
      "trechos": [[2, 10]]
    }
  ]
}
```

```sh
python ferramentas/cortar.py trabalhos/gravacoes/minha-live exemplos/cortes.json
node ferramentas/video.mjs trabalhos/cortes/2026-11-18-corte-melhor-momento
```

O MP4 sai em `trabalhos/cortes/2026-11-18-corte-melhor-momento/out/2026-11-18-corte-melhor-momento.mp4`, junto de `revisao.jpg`, uma folha de quadros para conferência. Se mudar `data` ou `slug`, use o caminho impresso pelo `cortar.py`.

Coloque vários itens em `cortes` para preparar mais de um vídeo. Rode `video.mjs` para cada pasta que quiser exportar. Para preparar apenas um corte, passe o `slug` como terceiro argumento de `cortar.py`.

## Gravar uma live em andamento

Passe o link de uma transmissão do YouTube ou de um canal da Twitch ou da Kick que esteja ao vivo.

```sh
python ferramentas/live.py "URL_DA_LIVE" --bloco 120 --max-horas 2
```

O terminal mostra a pasta criada em `trabalhos/gravacoes/`. A ferramenta grava em blocos e atualiza `transcricao.txt` conforme os transcreve. Em outro terminal, você já pode preparar cortes dos trechos que apareceram na transcrição. Use os segundos desde o começo da gravação, e confira `live.json` ou `live.log` para acompanhar o progresso.

Para encerrar, pressione Ctrl+C uma vez ou crie um arquivo vazio chamado `PARAR` na pasta mostrada no terminal. Aguarde o processamento dos blocos pendentes e a geração de `video.mp4`. Se o fluxo interromper, o gravador tenta reconectar. O tempo que ficou fora da gravação fica fora do vídeo.

| Opção | Para que serve |
| --- | --- |
| `--bloco 120` | Atualiza a transcrição em blocos de aproximadamente 2 minutos. O padrão é 300 segundos. |
| `--max-horas 2` | Limita a gravação a aproximadamente 2 horas. O padrão é 8 horas. |
| `--altura 720` | Prioriza uma resolução mais leve, conforme as qualidades disponíveis na plataforma. |
| `--modelo base` | Usa um modelo de transcrição menor que o `small` padrão. |
| `--threads 2` | Limita o número de threads de CPU dedicadas à transcrição ao vivo. |
| `--vocabulario "nome do jogo, nome do canal"` | Dá ao Whisper uma referência para nomes e termos que ele costuma confundir. |

Para outros parâmetros, use `python ferramentas/live.py --help`.

## Configurar o corte

- `trechos` aceita vários pares `[início, fim]` em segundos do original, em ordem e sem sobreposição. Exemplo `[[12.5, 24], [30, 41.2]]`.
- `layouts` começa no segundo zero e pode mudar com o vídeo original. Exemplo `[[0, "tela"], [42, "split"]]`. Se omitido, o padrão é `tela`.
- `canal` define o crédito. `url` e `plataforma` são opcionais. Se você preencher o link da Twitch, YouTube ou Kick, a ferramenta identifica a plataforma pelo domínio.
- `selo` é um texto curto opcional que aparece ao lado do crédito. `layouts`, `regioes` e `selo` podem ser definidos por corte.
- `data` usa `AAAA-MM-DD` e entra no nome da pasta. Se omitida, usa o dia atual. `slug` deve usar letras minúsculas sem acentos, números e hífens.

### Enquadramentos

| Layout | Como fica |
| --- | --- |
| `tela` | Mostra a tela horizontal sobre fundo desfocado. |
| `split` | Coloca o jogo em cima e a câmera embaixo. Configure `regioes.tela` e `regioes.camRet`. |
| `cam` | Dá destaque ao rosto. Use `regioes.camRet` se a câmera ocupa apenas parte da imagem. |
| `largo` | Mantém o quadro aberto para duas ou mais pessoas. |
| `jogo` | Recorta o gameplay para preencher a tela vertical e pode incluir a câmera em círculo. |
| `comp` | Mostra uma comparação lado a lado. Use `rotulos` no corte para nomear os dois lados. |

As coordenadas são em pixels da imagem normalizada para **1920 × 1080**, incluindo barras se houver. Para `tela` e `camRet`, informe `[x0, y0, x1, y1]`. Por exemplo, `"regioes": {"tela": [0, 0, 1920, 1080], "camRet": [1500, 700, 1900, 1060]}` coloca a câmera no canto inferior direito. Ajuste o retângulo à sua gravação. Os modos `jogo` e `comp` aceitam `regioes.jogo` e `regioes.comp` como `[x0, x1]`. Para o círculo em `jogo`, use `regioes.cam` como `[centroX, centroY, raio]`. Em `largo`, `regioes.largo` aceita `[x0, x1, y0]`. Em `cam` e `largo`, use `regioes.limiteY` para cortar o rodapé da imagem.

### Conferir antes de exportar

Gere só um quadro no segundo 3 do **corte**, com guias da área segura.

```sh
node ferramentas/video.mjs trabalhos/cortes/2026-11-18-corte-melhor-momento --quadro 3 --guias
```

O padrão é 1080 × 1920. Use `--leve` para reduzir a concorrência da renderização ou `--escala 0.75` para exportar em 810 × 1440. Para ajustar a cor do destaque e as fontes, edite [shared/tema/temas.ts](shared/tema/temas.ts).

## Problemas comuns

- **A transcrição está demorando.** Experimente `--modelo base`. Para gravações longas, `transcrever.py` guarda blocos intermediários e pode retomar uma transcrição interrompida com o mesmo comando.
- **O link não carrega.** Verifique se a live está acessível e atualize os extratores com `python -m pip install -U "yt-dlp[default]" streamlink`. Como alternativa, use um MP4 local com áudio.
- **O corte passa do fim da gravação.** Confira o último tempo da transcrição e diminua o fim do trecho. Se a live estiver no ar, aguarde o próximo bloco.
- **O render falha por memória.** Tente `--leve --escala 0.75` e evite várias exportações simultâneas.
- **Onde ficam os arquivos grandes?** Gravações e cortes ficam em `trabalhos/`, pasta ignorada pelo Git. Confira o espaço disponível antes de gravar por horas.

O renderizador usa o [Remotion](https://www.remotion.dev/docs/license). Consulte os termos do Remotion se for usar a ferramenta em uma organização.
