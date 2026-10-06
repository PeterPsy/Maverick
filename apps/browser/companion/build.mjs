import {collectRenderedContent} from "../broker/reading-actions.mjs";
import {readFileSync,readdirSync,mkdirSync,rmSync,writeFileSync} from "node:fs";
import {dirname,join} from "node:path";
import {fileURLToPath} from "node:url";
import {execFileSync} from "node:child_process";

const source=dirname(fileURLToPath(import.meta.url));
const target=join(source,"../frontend/public/companion");
rmSync(target,{recursive:true,force:true});mkdirSync(target,{recursive:true});
for(const name of readdirSync(source).sort()) {
  if(name === "build.mjs" || name.endsWith(".test.mjs"))continue;
  writeFileSync(join(target,name),readFileSync(join(source,name)));
}
writeFileSync(join(target,"reader.js"),`globalThis.maverickBrowserRead=${collectRenderedContent.toString()};\n`);
// A reproducible, dependency-free archive, downloadable from the app's public assets.
execFileSync("python3",["-c",[
  "import pathlib,sys,zipfile",
  "root=pathlib.Path(sys.argv[1])",
  "with zipfile.ZipFile(root.parent/'maverick-browser-companion.zip','w',zipfile.ZIP_DEFLATED) as archive:",
  " for path in sorted(root.iterdir()):",
  "  info=zipfile.ZipInfo('maverick-browser-companion/'+path.name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16",
  "  archive.writestr(info,path.read_bytes())",
].join("\n"),target]);
