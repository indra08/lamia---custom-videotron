// Read-only account inspection. Never print authentication material.
import {readFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import {join} from 'node:path';

const config = JSON.parse(await readFile(new URL('../config.local.json',import.meta.url),'utf8'));
let token = process.env.CLOUDFLARE_API_TOKEN;
if (!token) {
  for (const path of [join(homedir(),'Library/Preferences/.wrangler/config/default.toml'),
    join(homedir(),'.config/.wrangler/config/default.toml'),join(homedir(),'.wrangler/config/default.toml')]) {
    try {
      const text = await readFile(path,'utf8');
      token = /^oauth_token\s*=\s*"([^"]+)"/m.exec(text)?.[1];
      if (token) break;
    } catch (error) {if (error.code !== 'ENOENT') throw error;}
  }
}
if (!token) throw Error('Run wrangler login first or set CLOUDFLARE_API_TOKEN.');
for (const endpoint of ['workers/subdomain','workers/account-settings']) {
  const response = await fetch(`https://api.cloudflare.com/client/v4/accounts/${config.account_id}/${endpoint}`,
    {headers:{Authorization:'Bearer '+token},signal:AbortSignal.timeout(20000)});
  const data = await response.json();
  if (!data.success) throw Error('Could not inspect '+endpoint+'; Cloudflare HTTP '+response.status);
  if (endpoint === 'workers/subdomain') console.log(JSON.stringify({subdomain:data.result.subdomain}));
  else console.log(JSON.stringify({workers_settings:data.result}));
}
