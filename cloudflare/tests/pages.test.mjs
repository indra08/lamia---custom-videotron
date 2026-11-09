import {test} from 'node:test';
import assert from 'node:assert/strict';
import pages from '../src/pages.mjs';

test('Pages forwards API requests with the original origin, auth, cookie, method and body',async () => {
  const request = new Request('https://lamia-id.pages.dev/api/v1/admin/auth/login',{method:'POST',
    headers:{Origin:'https://lamia-id.pages.dev','Content-Type':'application/json',Cookie:'session=test',Authorization:'Bearer test'},
    body:JSON.stringify({username:'test'})});
  let received;
  const response = await pages.fetch(request,{APP:{fetch:async incoming=>{
    received=incoming;return Response.json({ok:true},{headers:{'Set-Cookie':'test=value; Secure; HttpOnly'}});
  }}});
  assert.equal(received,request);assert.equal(received.url,request.url);
  assert.equal(received.headers.get('Origin'),'https://lamia-id.pages.dev');
  assert.equal(received.headers.get('Cookie'),'session=test');assert.equal(received.headers.get('Authorization'),'Bearer test');
  assert.deepEqual(await received.json(),{username:'test'});
  assert.match(response.headers.get('Set-Cookie'),/Secure; HttpOnly/);
});

test('Pages sends protected routes to the backend and static routes to Pages assets',async () => {
  const env={APP:{fetch:async()=>new Response('backend',{status:303,headers:{Location:'/login'}})},
    ASSETS:{fetch:async()=>new Response('asset')}};
  for(const path of ['/admin','/schedule','/player','/static/player.html','/login','/status','/api/v1/screens']) {
    assert.equal((await pages.fetch(new Request('https://lamia-id.pages.dev'+path),env)).status,303,path);
  }
  for(const path of ['/','/static/app.js','/icon/logo.webp']) {
    assert.equal(await (await pages.fetch(new Request('https://lamia-id.pages.dev'+path),env)).text(),'asset',path);
  }
});

test('Pages does not serve a protected static file when the backend binding is missing',async () => {
  const result=await pages.fetch(new Request('https://lamia-id.pages.dev/static/player.html'),{
    ASSETS:{fetch:async()=>new Response('should not be served')}});
  assert.equal(result.status,503);assert.equal(result.headers.get('Cache-Control'),'no-store');
});
