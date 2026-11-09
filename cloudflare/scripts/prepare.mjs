import {cp, mkdir, readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import './prepare-fonts.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = async name => JSON.parse(await readFile(resolve(root, name), 'utf8'));
let config;
try { config = await read('config.local.json'); }
catch (error) {
  if (error.code !== 'ENOENT') throw error;
  config = await read('config.example.json');
}
const generated = resolve(root, '.generated');
await mkdir(generated, {recursive:true});
await cp(resolve(root, '../static'), resolve(generated, 'public/static'), {recursive:true});
await cp(resolve(root, '../icon'), resolve(generated, 'public/icon'), {recursive:true});
await cp(resolve(root, '../static/index.html'), resolve(generated, 'public/index.html'));
await cp(resolve(root, '../icon/logo.ico'), resolve(generated, 'public/favicon.ico'));

// Only the Cloudflare copy changes: Cron runs once per minute, not every 5 seconds.
const appPath = resolve(generated, 'public/static/app.js');
const app = await readFile(appPath, 'utf8');
await writeFile(appPath, app.replace('Rekonsiliasi otomatis setiap 5 detik.',
  'Rekonsiliasi setiap menit dan saat player menyinkronkan jadwal.'));
const playerPath = resolve(generated,'public/static/player.js');
const player = await readFile(playerPath,'utf8');
await writeFile(playerPath,player.replace('.slice(0,100);','.slice(0,20);'));
const wrangler = {
  name:config.name,
  main:'../src/worker.mjs',
  compatibility_date:'2026-11-01',
  workers_dev:true,
  preview_urls:false,
  assets:{directory:'./public', binding:'ASSETS', html_handling:'none',
    run_worker_first:['/api/*','/admin','/schedule','/login','/player','/static/player.html','/terms','/privacy','/status']},
  d1_databases:[{binding:'DB', database_name:config.database_name,
    database_id:config.database_id || '00000000-0000-0000-0000-000000000000', migrations_dir:'../migrations'}],
  kv_namespaces:[{binding:'MEDIA', id:config.media_namespace_id || '00000000000000000000000000000000'}],
  triggers:{crons:['* * * * *']},
  rules:[{type:'Data', globs:['**/*.ttf','**/*.png','**/*.pdf'], fallthrough:true}],
  vars:{...config.vars, APP_ENV:'cloudflare'},
  observability:{enabled:false}
};
if (config.account_id) wrangler.account_id = config.account_id;
await writeFile(resolve(generated, 'wrangler.json'), JSON.stringify(wrangler, null, 2)+'\n');
// Local Worker secrets are copied only into the ignored Cloudflare build directory.
try {await cp(resolve(root,'.dev.vars'),resolve(generated,'.dev.vars'));}
catch(error){if(error.code !== 'ENOENT')throw error;}
console.log('Cloudflare config/assets prepared in cloudflare/.generated; original setup unchanged.');
