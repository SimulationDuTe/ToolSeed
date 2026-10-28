import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const here=new URL('./',import.meta.url);
await fs.mkdir(new URL('lib/',here),{recursive:true});
await fs.copyFile(new URL('../shared/learning-state.mjs',here),new URL('lib/learning-state.mjs',here));
const source=await fs.readFile(new URL('../../toolseed/ui_assets/app.js',here),'utf8');
const start='// TOOLSEED_SHARED_VIEWS_START',end='// TOOLSEED_SHARED_VIEWS_END';
if(source.split(start).length!==2||source.split(end).length!==2)throw new Error('Shared GUI view boundaries missing or duplicated');
const views=source.split(start)[1].split(end)[0];
const styleSource=await fs.readFile(new URL('../../toolseed/ui_assets/app.css',here),'utf8');
const styleStart='/* TOOLSEED_SHARED_STYLES_START */',styleEnd='/* TOOLSEED_SHARED_STYLES_END */';
if(styleSource.split(styleStart).length!==2||styleSource.split(styleEnd).length!==2)throw new Error('Shared GUI style boundaries missing or duplicated');
const client=await fs.readFile(new URL('src/client.cjs',here),'utf8');
const styles=styleSource.split(styleStart)[1].split(styleEnd)[0]+await fs.readFile(new URL('src/native.css',here),'utf8');
// Reuse escaped presentation functions; the native SDK owns controls and theme.
const bundle=`window.__ModuleLoader__.load({id:"dsh-toolseed",factory:(require)=>{
var module={exports:{}};
const nativeStyles=${JSON.stringify(styles)};
const views=(()=>{${views}
return {summary,capabilityCards,activityCards,capabilityTitle,capabilityDetail,activityDetail,eventTitle,filterCapabilities,readScreen,readCapability,testMarked,verificationText};})();
${client}
return module.exports;}});
`;
await fs.mkdir(new URL('lib/',here),{recursive:true});
await fs.writeFile(new URL('lib/client.js',here),bundle);
console.log('Built native ToolSeed settings page → '+fileURLToPath(new URL('lib/client.js',here)));
