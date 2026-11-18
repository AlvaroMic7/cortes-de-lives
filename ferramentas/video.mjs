import {spawnSync} from 'node:child_process';
import {copyFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';

const raiz = fileURLToPath(new URL('../', import.meta.url));
const require = createRequire(import.meta.url);
const uso = 'Uso: node ferramentas/video.mjs <pasta-do-corte> [--leve] [--escala 0.75] [--quadro 3.5] [--guias]';

function rodar(programa, argumentos, capturar = false) {
  const resultado = spawnSync(programa, argumentos, {
    cwd: raiz,
    stdio: capturar ? 'pipe' : 'inherit',
    encoding: 'utf8',
  });
  if (resultado.error) throw resultado.error;
  if (resultado.status !== 0) {
    if (capturar && resultado.stderr) console.error(resultado.stderr.trim());
    throw new Error(`${path.basename(programa)} terminou com código ${resultado.status ?? resultado.signal}.`);
  }
  return resultado;
}

function entradaTemporaria(execucao, pasta) {
  copyFileSync(path.join(pasta, 'corte.json'), path.join(execucao, 'corte.json'));
  copyFileSync(path.join(pasta, 'sinc.json'), path.join(execucao, 'sinc.json'));
  const pub = path.join(execucao, 'public');
  mkdirSync(path.join(pub, 'corte'), {recursive: true});
  copyFileSync(path.join(pasta, 'fonte.mp4'), path.join(pub, 'corte', 'fonte.mp4'));
  cpSync(path.join(raiz, 'shared', 'audio'), path.join(pub, 'audio'), {recursive: true});

  const entrada = path.join(execucao, 'index.tsx');
  writeFileSync(entrada, `import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {criarCorte, type DadosCorte} from '../../render/Corte';
import corte from './corte.json';
import sinc from './sinc.json';

const dados = corte as DadosCorte;
const Video = criarCorte(dados);
const duracao = dados.planos.reduce((total, plano) => total + plano.dur, 0);
const Root = () => (
  <Composition
    id="Corte"
    component={Video}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={duracao}
    defaultProps={{sinc, pasta: 'corte', guias: false}}
  />
);
registerRoot(Root);
`);
  return {entrada, pub};
}

function exportar(bruto, final, revisao, duracao) {
  const alvo = 'I=-14:TP=-1.5:LRA=11';
  const {stderr} = rodar('ffmpeg', ['-hide_banner', '-i', bruto, '-af', `loudnorm=${alvo}:print_format=json`, '-f', 'null', '-'], true);
  const medicao = JSON.parse(/\{[^{}]*"input_i"[^{}]*\}/.exec(stderr)?.[0] ?? '{}');
  const filtro = Number.isFinite(Number(medicao.input_i))
    ? `loudnorm=${alvo}:measured_I=${medicao.input_i}:measured_TP=${medicao.input_tp}:measured_LRA=${medicao.input_lra}:measured_thresh=${medicao.input_thresh}:offset=${medicao.target_offset}:linear=true`
    : `loudnorm=${alvo}`;
  rodar('ffmpeg', ['-v', 'error', '-y', '-i', bruto, '-af', filtro, '-c:v', 'libx264', '-preset', 'medium', '-crf', '25',
    '-maxrate', '5M', '-bufsize', '10M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', final]);

  const passo = Math.max(1 / 30, duracao / 24).toFixed(5);
  rodar('ffmpeg', ['-v', 'error', '-y', '-i', final, '-vf', `fps=1/${passo},scale=216:-2,tile=6x4`,
    '-frames:v', '1', '-update', '1', revisao]);
}

function main() {
  const {values, positionals} = parseArgs({
    options: {help: {type: 'boolean', short: 'h'}, leve: {type: 'boolean'}, guias: {type: 'boolean'},
      quadro: {type: 'string'}, escala: {type: 'string'}},
    allowPositionals: true,
  });
  if (values.help) {
    console.log(uso);
    return;
  }
  if (positionals.length !== 1) throw new Error(uso);

  const pasta = path.resolve(positionals[0]);
  for (const nome of ['fonte.mp4', 'corte.json', 'sinc.json']) {
    if (!existsSync(path.join(pasta, nome))) throw new Error(`Arquivo ausente: ${path.join(pasta, nome)}. Rode cortar.py primeiro.`);
  }
  const dados = JSON.parse(readFileSync(path.join(pasta, 'corte.json'), 'utf8'));
  const duracao = dados.planos.reduce((total, plano) => total + plano.dur, 0) / 30;
  const segundo = values.quadro === undefined ? undefined : Number(values.quadro);
  const escala = values.escala === undefined ? 1 : Number(values.escala);
  if (segundo !== undefined && !(segundo >= 0 && Math.round(segundo * 30) < Math.round(duracao * 30))) {
    throw new Error(`--quadro deve indicar um segundo dentro do corte (${duracao.toFixed(2)} s).`);
  }
  if (!(escala > 0 && escala <= 1)) throw new Error('--escala deve estar entre 0 e 1, sem incluir o zero.');

  const pastaRender = path.join(raiz, '.render');
  mkdirSync(pastaRender, {recursive: true});
  const execucao = mkdtempSync(path.join(pastaRender, 'exec-'));
  const out = path.join(pasta, 'out');
  mkdirSync(out, {recursive: true});
  try {
    const {entrada, pub} = entradaTemporaria(execucao, pasta);
    const cli = path.join(path.dirname(require.resolve('@remotion/cli/package.json')), 'remotion-cli.js');
    const remotion = (comando, arquivo, ...opcoes) => rodar(process.execPath, [
      cli, comando, entrada, 'Corte', arquivo, `--public-dir=${pub}`,
      `--props=${JSON.stringify({guias: Boolean(values.guias)})}`, '--log=error', ...opcoes,
    ]);
    if (segundo !== undefined) {
      const nome = `quadro-${String(segundo).replace('.', '_')}${values.guias ? '-guias' : ''}.png`;
      const png = path.join(out, nome);
      remotion('still', png, `--frame=${Math.round(segundo * 30)}`);
      console.log(`Quadro: ${png}`);
      return;
    }

    const bruto = path.join(execucao, 'bruto.mp4');
    remotion('render', bruto, '--crf=16', '--timeout=180000', `--concurrency=${values.leve ? 1 : 2}`,
      '--offthreadvideo-cache-size-in-bytes=268435456', '--offthreadvideo-video-threads=2', `--scale=${escala}`);
    const pronto = path.join(execucao, 'pronto.mp4');
    const grade = path.join(execucao, 'revisao.jpg');
    exportar(bruto, pronto, grade, duracao);
    const sufixo = values.guias ? '-guias' : '';
    const final = path.join(out, `${path.basename(pasta)}${sufixo}.mp4`);
    const revisao = path.join(out, `revisao${sufixo}.jpg`);
    renameSync(pronto, final);
    if (existsSync(grade)) renameSync(grade, revisao);
    console.log(`Pronto: ${final}`);
    if (existsSync(revisao)) console.log(`Revisão: ${revisao}`);
  } finally {
    rmSync(execucao, {recursive: true, force: true});
  }
}

try {
  main();
} catch (erro) {
  console.error(erro.message);
  process.exitCode = 1;
}
