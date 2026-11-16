export function basename(path){if(typeof path!=="string"||!path.trim())return"";return path.replaceAll("\\","/").split("/").at(-1)||""}
export function extension(path){const name=basename(path),i=name.lastIndexOf(".");return i>0?name.slice(i+1).toLowerCase():""}
