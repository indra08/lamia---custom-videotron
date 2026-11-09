import {readFile,writeFile} from 'node:fs/promises';
import {parseEnv} from 'node:util';
import {randomBytes} from 'node:crypto';

const root = new URL('../',import.meta.url);
const sourcePath = new URL('../../.env',import.meta.url);
const original = await readFile(sourcePath,'utf8');
const source = parseEnv(original);
const configPath = new URL('config.local.json',root);
const config = JSON.parse(await readFile(configPath,'utf8'));
const secretsPath = new URL('.secrets.json',root);
let secrets;
try {secrets = JSON.parse(await readFile(secretsPath,'utf8'));}
catch(error){if(error.code !== 'ENOENT')throw error;secrets={APP_SECRET:randomBytes(48).toString('base64url'),ADMIN_PASSWORD:randomBytes(24).toString('base64url')};}
const publicKeys = ['ADMIN_USERNAME','OPERATOR_NAME','OPERATOR_ADDRESS','SUPPORT_EMAIL',
  'BANK_NAME','BANK_ACCOUNT','BANK_HOLDER','SMTP_HOST','SMTP_PORT','SMTP_SECURE','SMTP_ENCRYPTION',
  'SMTP_FROM','PHONE_OTP_WEBHOOK_URL'];
const copied = [], skipped = [];
for (const key of publicKeys) {
  if (!Object.hasOwn(source,key))continue;
  if (key === 'BANK_ACCOUNT' && source[key] === '12345678901234567890') {
    config.vars[key] = ''; skipped.push('BANK_ACCOUNT: sample account; checkout stays disabled');continue;
  }
  if (key === 'PHONE_OTP_WEBHOOK_URL' && source[key] && !source[key].startsWith('https://')) {
    skipped.push('PHONE_OTP_WEBHOOK_URL: HTTPS required');continue;
  }
  config.vars[key] = source[key];copied.push(key);
}
for (const key of ['APP_SECRET','ADMIN_PASSWORD','SMTP_USERNAME','SMTP_PASSWORD','PHONE_OTP_WEBHOOK_TOKEN']) {
  if (!Object.hasOwn(source,key))continue;
  const minimum = key === 'APP_SECRET'?32:key === 'ADMIN_PASSWORD'?10:0;
  if (minimum && (source[key].length < minimum || source[key].startsWith('replace-'))) {
    skipped.push(`${key}: source does not meet Cloudflare minimum ${minimum}; dedicated secret retained`);continue;
  }
  secrets[key]=source[key];copied.push(key+' (encrypted secret)');
  if(key === 'ADMIN_PASSWORD')config.vars.ADMIN_PASSWORD_MIN_LENGTH=source[key].length<12?'10':'12';
}
// PUBLIC_BASE_URL, APP_ENV, database paths, local bind settings and demo switches
// stay under Cloudflare configuration. Never copy localhost/development settings.
await writeFile(configPath,JSON.stringify(config,null,2)+'\n',{mode:0o600});
await writeFile(secretsPath,JSON.stringify(secrets,null,2)+'\n',{mode:0o600});
await writeFile(new URL('.dev.vars',root),Object.entries(secrets).map(([k,v])=>k+'='+JSON.stringify(v)).join('\n')+'\n',{mode:0o600});
if (await readFile(sourcePath,'utf8') !== original)throw Error('Source .env changed during import; inspect before deployment.');
console.log(JSON.stringify({copied,skipped,source_unchanged:true},null,2));
