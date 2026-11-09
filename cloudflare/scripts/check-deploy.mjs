import {readFile} from 'node:fs/promises';
const path = new URL('../config.local.json', import.meta.url);
let config;
try {config = JSON.parse(await readFile(path, 'utf8'));}
catch {throw Error('Create cloudflare/config.local.json from config.example.json before deploying.');}
if (!/^[\da-f-]{36}$/i.test(config.database_id || '') || /^0+-/.test(config.database_id)) {
  throw Error('Set the dedicated Cloudflare D1 database_id before deploying.');
}
if (!config.vars?.PUBLIC_BASE_URL?.startsWith('https://')) {
  throw Error('Set PUBLIC_BASE_URL to the public HTTPS application URL before deploying.');
}
if (!/^[\da-f]{32}$/i.test(config.media_namespace_id || '') || /^0+$/.test(config.media_namespace_id)) {
  throw Error('Set the dedicated Workers KV media_namespace_id before deploying.');
}
console.log('Dedicated Cloudflare deployment configuration checked.');
const secrets = JSON.parse(await readFile(new URL('../.secrets.json',import.meta.url),'utf8'));
const passwordMinimum=config.vars.ADMIN_PASSWORD_MIN_LENGTH === '10'?10:12;
for (const [key,minimum] of [['APP_SECRET',32],['ADMIN_PASSWORD',passwordMinimum]]) {
  if (typeof secrets[key] !== 'string' || secrets[key].length < minimum || secrets[key].startsWith('replace-')) {
    throw Error('Set a unique '+key+' in cloudflare/.secrets.json before deploying.');
  }
}
