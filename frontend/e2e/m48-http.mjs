import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
const script=readFileSync('public/sw.js');
createServer((request,response)=>{
  if(request.url.startsWith('/sw.js')) response.writeHead(200, {'Content-Type':'application/javascript'}).end(script);
  else response.writeHead(200, {'Content-Type':'text/html'}).end('<title>Worker check</title>');
}).listen(3100,'127.0.0.1');
