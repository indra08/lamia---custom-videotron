// Embed fonts/logo at build time; Worker requests never run fontkit/subsetting.
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {PDFDocument} from 'pdf-lib';
import fontkit from '@pdf-lib/fontkit';

const root = new URL('../',import.meta.url);
await mkdir(new URL('.generated/',root),{recursive:true});
const pdf = await PDFDocument.create(); pdf.registerFontkit(fontkit);
pdf.addPage([595.28,841.89]);
const metrics = {};
for (const [key,file] of [['regular','Vera.ttf'],['strong','VeraBd.ttf']]) {
  const bytes = new Uint8Array(await readFile(new URL('assets/'+file,root)));
  const parsed = fontkit.create(bytes), font = await pdf.embedFont(bytes,{subset:false});
  const chars = {};
  for (const code of parsed.characterSet) {
    const glyph = parsed.glyphForCodePoint(code);
    chars[code] = [glyph.id.toString(16).padStart(4,'0'),glyph.advanceWidth/parsed.unitsPerEm];
  }
  metrics[key] = {ref:font.ref.objectNumber,generation:font.ref.generationNumber,name:font.name,chars,
    height:(parsed.ascent-parsed.descent)/parsed.unitsPerEm};
}
const logo = await pdf.embedPng(await readFile(new URL('assets/logo.png',root)));
metrics.logo = {ref:logo.ref.objectNumber,generation:logo.ref.generationNumber,width:logo.width,height:logo.height};
await writeFile(new URL('.generated/invoice-template.pdf',root),await pdf.save());
await writeFile(new URL('.generated/font-metrics.json',root),JSON.stringify(metrics));
