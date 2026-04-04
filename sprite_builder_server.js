const http=require('node:http');
const fs=require('node:fs/promises');
const path=require('node:path');

const HOST='localhost';
const PORT=Number(process.env.PORT||8080);
const ROOT_DIR=__dirname;
const STYLE_FILE=path.join(ROOT_DIR,'style.json');
const HTML_FILE=path.join(ROOT_DIR,'sprite_builder.html');
const GENERATED_DIR=path.join(ROOT_DIR,'generated_sprite');
const SPRITE_JSON_FILE=path.join(GENERATED_DIR,'sprite.json');
const SPRITE_PNG_FILE=path.join(GENERATED_DIR,'sprite.png');
const MAPTOOLKIT_BASE='https://dataconnector.maptoolkit.net/maptoolkit/';
const MAPTOOLKIT_PROXY_PREFIX='/maptoolkit/';
const MAX_BODY_BYTES=50*1024*1024;
const FALLBACK_SPRITE_PNG=Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAffR6iwAAAABJRU5ErkJggg==',
  'base64'
);

function stripJsonComments(text){
  let out='';
  let inString=false;
  let escaped=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];
    const next=text[i+1];
    if(inString){
      out+=ch;
      if(escaped){
        escaped=false;
      }else if(ch==='\\'){
        escaped=true;
      }else if(ch==='"'){
        inString=false;
      }
      continue;
    }
    if(ch==='"'){
      inString=true;
      out+=ch;
      continue;
    }
    if(ch==='/'&&next==='/'){
      while(i<text.length&&text[i]!=='\n') i++;
      if(i<text.length) out+='\n';
      continue;
    }
    out+=ch;
  }
  return out;
}

function requestOrigin(req){
  return `http://${req.headers.host||`${HOST}:${PORT}`}`;
}

function setCommonHeaders(res,contentType){
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Access-Control-Allow-Methods','GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers','Content-Type');
  res.setHeader('Cache-Control','no-store');
  if(contentType) res.setHeader('Content-Type',contentType);
}

function sendText(res,status,body,contentType='text/plain; charset=utf-8'){
  setCommonHeaders(res,contentType);
  res.writeHead(status);
  res.end(body);
}

function sendJson(res,status,payload){
  sendText(res,status,JSON.stringify(payload,null,2),'application/json; charset=utf-8');
}

async function readRequestBody(req){
  const chunks=[];
  let total=0;
  for await(const chunk of req){
    total+=chunk.length;
    if(total>MAX_BODY_BYTES){
      throw new Error('Request body zu gross');
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

async function loadSanitizedStyle(origin){
  const raw=await fs.readFile(STYLE_FILE,'utf8');
  const style=JSON.parse(stripJsonComments(raw));
  style.sprite=`${origin}/sprite/sprite`;
  Object.values(style.sources||{}).forEach(source=>{
    if(typeof source.url==='string') source.url=rewriteMapToolkitUrl(source.url,origin);
    if(Array.isArray(source.tiles)) source.tiles=source.tiles.map(tile=>rewriteMapToolkitUrl(tile,origin));
  });
  style.layers=(style.layers||[]).filter(layer=>!(layer.id||'').startsWith('TEST_'));
  return style;
}

function rewriteMapToolkitUrl(value,origin){
  if(typeof value!=='string'||!value.startsWith(MAPTOOLKIT_BASE)) return value;
  return `${origin}${MAPTOOLKIT_PROXY_PREFIX}${value.slice(MAPTOOLKIT_BASE.length)}`;
}

function rewriteMapToolkitPayload(value,origin){
  if(typeof value==='string') return rewriteMapToolkitUrl(value,origin);
  if(Array.isArray(value)) return value.map(item=>rewriteMapToolkitPayload(item,origin));
  if(!value||typeof value!=='object') return value;
  return Object.fromEntries(
    Object.entries(value).map(([key,item])=>[key,rewriteMapToolkitPayload(item,origin)])
  );
}

function mimeType(filePath){
  const ext=path.extname(filePath).toLowerCase();
  if(ext==='.html') return 'text/html; charset=utf-8';
  if(ext==='.js') return 'application/javascript; charset=utf-8';
  if(ext==='.css') return 'text/css; charset=utf-8';
  if(ext==='.json') return 'application/json; charset=utf-8';
  if(ext==='.png') return 'image/png';
  if(ext==='.svg') return 'image/svg+xml';
  return 'application/octet-stream';
}

async function sendFile(res,filePath){
  const data=await fs.readFile(filePath);
  setCommonHeaders(res,mimeType(filePath));
  res.writeHead(200);
  res.end(data);
}

async function saveSprite(body){
  const payload=JSON.parse(body||'{}');
  if(!payload.spriteJson||typeof payload.spriteJson!=='object'){
    throw new Error('spriteJson fehlt');
  }
  if(typeof payload.spritePngDataUrl!=='string'){
    throw new Error('spritePngDataUrl fehlt');
  }
  const match=payload.spritePngDataUrl.match(/^data:image\/png;base64,(.+)$/);
  if(!match){
    throw new Error('spritePngDataUrl ist kein PNG-Data-URL');
  }
  await fs.mkdir(GENERATED_DIR,{recursive:true});
  await fs.writeFile(SPRITE_JSON_FILE,JSON.stringify(payload.spriteJson,null,2),'utf8');
  await fs.writeFile(SPRITE_PNG_FILE,Buffer.from(match[1],'base64'));
}

async function proxyMapToolkit(req,res,url){
  const upstreamPath=url.pathname.slice(MAPTOOLKIT_PROXY_PREFIX.length);
  const upstreamUrl=MAPTOOLKIT_BASE+upstreamPath+url.search;
  const upstreamRes=await fetch(upstreamUrl,{
    headers:{
      'Referer':`${requestOrigin(req)}/`,
      'User-Agent':'Sprite Builder MapToolkit Proxy'
    }
  });
  const contentType=upstreamRes.headers.get('content-type')||'application/octet-stream';
  if(contentType.includes('application/json')){
    const text=await upstreamRes.text();
    try{
      const payload=rewriteMapToolkitPayload(JSON.parse(text),requestOrigin(req));
      sendJson(res,upstreamRes.status,payload);
    }catch(e){
      sendText(res,upstreamRes.status,text,contentType);
    }
    return;
  }
  const body=Buffer.from(await upstreamRes.arrayBuffer());
  setCommonHeaders(res,contentType);
  res.writeHead(upstreamRes.status);
  res.end(body);
}

async function serveStatic(reqPath,res){
  const filePath=reqPath==='/' ? HTML_FILE : path.resolve(ROOT_DIR,'.'+reqPath);
  const rootPrefix=ROOT_DIR.endsWith(path.sep)?ROOT_DIR:ROOT_DIR+path.sep;
  if(filePath!==ROOT_DIR&&!filePath.startsWith(rootPrefix)){
    sendText(res,403,'Forbidden');
    return;
  }
  try{
    await sendFile(res,filePath);
  }catch(e){
    sendText(res,404,'Not found');
  }
}

async function handleRequest(req,res){
  const url=new URL(req.url,requestOrigin(req));
  if(req.method==='OPTIONS'){
    setCommonHeaders(res,'text/plain; charset=utf-8');
    res.writeHead(204);
    res.end();
    return;
  }
  try{
    if(req.method==='GET'&&url.pathname.startsWith(MAPTOOLKIT_PROXY_PREFIX)){
      await proxyMapToolkit(req,res,url);
      return;
    }
    if(req.method==='GET'&&url.pathname==='/style.json'){
      sendJson(res,200,await loadSanitizedStyle(requestOrigin(req)));
      return;
    }
    if(req.method==='GET'&&url.pathname==='/sprite/sprite.json'){
      try{
        await sendFile(res,SPRITE_JSON_FILE);
      }catch(e){
        sendJson(res,200,{});
      }
      return;
    }
    if(req.method==='GET'&&url.pathname==='/sprite/sprite.png'){
      try{
        await sendFile(res,SPRITE_PNG_FILE);
      }catch(e){
        setCommonHeaders(res,'image/png');
        res.writeHead(200);
        res.end(FALLBACK_SPRITE_PNG);
      }
      return;
    }
    if(req.method==='POST'&&url.pathname==='/api/sprite'){
      await saveSprite(await readRequestBody(req));
      sendJson(res,200,{ok:true,sprite:requestOrigin(req)+'/sprite/sprite'});
      return;
    }
    if(req.method==='GET'){
      await serveStatic(url.pathname,res);
      return;
    }
    sendText(res,405,'Method not allowed');
  }catch(e){
    sendText(res,500,e&&e.message?e.message:String(e));
  }
}

if(require.main===module){
  http.createServer((req,res)=>{
    handleRequest(req,res);
  }).listen(PORT,HOST,()=>{
    console.log(`Sprite Builder Server: http://${HOST}:${PORT}`);
    console.log(`HTML: http://${HOST}:${PORT}/sprite_builder.html`);
    console.log(`Style: http://${HOST}:${PORT}/style.json`);
    console.log(`Sprite: http://${HOST}:${PORT}/sprite/sprite`);
  });
}

module.exports={
  stripJsonComments,
  loadSanitizedStyle,
  saveSprite,
  handleRequest
};
