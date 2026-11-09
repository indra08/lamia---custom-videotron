import {PDFDocument,PDFFont,PDFImage,PDFRef,PDFHexString,CustomFontEmbedder,PngEmbedder} from 'pdf-lib';
import template from '../.generated/invoice-template.pdf';
import metrics from '../.generated/font-metrics.json';

// The template already contains complete fonts and the logo. Reuse their object references.
// Encoding/measurement uses build-time metrics; fontkit never executes inside a Worker.
class PreparedFont extends CustomFontEmbedder {
  constructor(info) {
    super({unitsPerEm:1000,postscriptName:info.name,characterSet:[]},new Uint8Array());
    this.info = info;
  }
  glyph(character) {return this.info.chars[character.codePointAt(0)] || this.info.chars[63];}
  encodeText(text) {return PDFHexString.of([...text].map(c=>this.glyph(c)[0]).join(''));}
  widthOfTextAtSize(text,size) {let width=0;for(const c of text)width+=this.glyph(c)[1];return width*size;}
  heightOfFontAtSize(size) {return this.info.height*size;}
  sizeOfFontAtHeight(height) {return height/this.info.height;}
  async embedIntoContext(context,ref) {return ref;}
}

export async function preparedInvoice() {
  const pdf = await PDFDocument.load(template,{updateMetadata:false});
  pdf.removePage(0);
  const font = key => {
    const info = metrics[key];
    return PDFFont.of(PDFRef.of(info.ref,info.generation),pdf,new PreparedFont(info));
  };
  const image = PDFImage.of(PDFRef.of(metrics.logo.ref,metrics.logo.generation),pdf,
    new PngEmbedder({width:metrics.logo.width,height:metrics.logo.height,bitsPerComponent:8}));
  return {pdf,font:font('regular'),bold:font('strong'),image};
}
