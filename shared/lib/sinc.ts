export type Palavra = {t: string; ini: number; fim: number; cena?: string};
export type CenaSinc = {id: string; titulo: string; ini: number; fim: number};
export type Sinc = {duracao: number; palavras: Palavra[]; cenas: CenaSinc[]};
