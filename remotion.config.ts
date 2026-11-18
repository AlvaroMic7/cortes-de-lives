import path from 'node:path';
import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.overrideWebpackConfig((c) => ({
  ...c,
  resolve: {...c.resolve, alias: {...(c.resolve?.alias ?? {}), '@shared': path.join(process.cwd(), 'shared')}},
}));
