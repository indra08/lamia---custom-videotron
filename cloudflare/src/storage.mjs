import {batch, statement, guard, now, fail} from './core.mjs';

// Leave space below KV's account-wide Free allowance for eventual deletes and other usage.
// This is an application cap, not an account billing cap.
export const MEDIA_CAP = 800 * 1024 * 1024;

export async function putMedia(env, key, bytes, mime) {
  const size = bytes.byteLength;
  await batch(env, [
    guard(env, 'NOT EXISTS(SELECT 1 FROM media_objects WHERE key=?)',key),
    guard(env, '(SELECT COALESCE(SUM(size),0) FROM media_objects)+?<=?',size,MEDIA_CAP),
    statement(env, 'INSERT INTO media_objects VALUES(?,?,?)',key,size,now())
  ]);
  try {
    // Unique keys are immutable: a later content version always gets a new key.
    const value = bytes.buffer.slice(bytes.byteOffset || 0,(bytes.byteOffset || 0)+size);
    await env.MEDIA.put(key,value,{metadata:{size,mime}});
  } catch (error) {
    await statement(env,'DELETE FROM media_objects WHERE key=?',key).run();
    throw error;
  }
}

export async function deleteMedia(env,key) {
  await env.MEDIA.delete(key);
  await statement(env,'DELETE FROM media_objects WHERE key=?',key).run();
}

export async function readMedia(env,key,type='stream') {
  return env.MEDIA.getWithMetadata(key,{type,cacheTtl:60});
}

export function sliceStream(input,offset,length) {
  let skipped = 0, remaining = length;
  const reader = input.getReader();
  return new ReadableStream({
    async pull(controller) {
      try {
        while (remaining > 0) {
          const {value,done} = await reader.read();
          if (done) {controller.close();return;}
          const start = Math.min(value.byteLength,Math.max(0,offset-skipped));
          skipped += value.byteLength;
          const chunk = value.subarray(start,start+remaining);
          if (chunk.byteLength) {
            controller.enqueue(chunk); remaining -= chunk.byteLength;
            if (!remaining) {controller.close();await reader.cancel();}
            return;
          }
        }
        controller.close();
      } catch (error) {controller.error(error);}
    },
    cancel(reason) {return reader.cancel(reason);}
  });
}
