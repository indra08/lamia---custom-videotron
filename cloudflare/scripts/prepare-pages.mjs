import './prepare.mjs';
import {cp,mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {appPaths} from '../src/pages.mjs';

const root = fileURLToPath(new URL('../',import.meta.url));
let config;
try {config = JSON.parse(await readFile(resolve(root,'config.local.json'),'utf8'));}
catch(error){if(error.code !== 'ENOENT')throw error;config = JSON.parse(await readFile(resolve(root,'config.example.json'),'utf8'));}
const directory = resolve(root,'.generated/pages');
await mkdir(directory,{recursive:true});
await cp(resolve(root,'.generated/public'),resolve(directory,'public'),{recursive:true,
  filter:path=>path !== resolve(root,'.generated/public/static/player.html')});
await cp(resolve(root,'src/pages.mjs'),resolve(directory,'public/_worker.js'));
await writeFile(resolve(directory,'public/_routes.json'),JSON.stringify({version:1,
  include:['/api','/api/*',...appPaths],exclude:[]},null,2)+'\n');
await writeFile(resolve(directory,'public/404.html'),'<!doctype html><html lang="id"><meta charset="utf-8"><title>LAMIA</title><h1>Halaman tidak ditemukan</h1><a href="/">Kembali ke LAMIA</a></html>\n');
const pages = {name:config.pages_project || 'lamia-id',pages_build_output_dir:'./public',
  compatibility_date:'2026-11-01',services:[{binding:'APP',service:config.name}]};
await writeFile(resolve(directory,'wrangler.json'),JSON.stringify(pages,null,2)+'\n');
console.log('Pages assets and backend service binding prepared in cloudflare/.generated/pages.');
