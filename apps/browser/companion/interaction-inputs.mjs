export const interactionActions = new Set(["click", "type", "press_key", "hover", "select_option", "set_checked"]);
export const interactionFields = {
  click:["ref"], hover:["ref"], type:["ref","text"], press_key:["ref","key"],
  select_option:["ref","values"], set_checked:["ref","checked"],
};
const keys={Enter:["Enter",13],Tab:["Tab",9],Escape:["Escape",27],Backspace:["Backspace",8],Delete:["Delete",46],Space:[" ",32],
  ArrowUp:["ArrowUp",38],ArrowDown:["ArrowDown",40],ArrowLeft:["ArrowLeft",37],ArrowRight:["ArrowRight",39],Home:["Home",36],End:["End",35],PageUp:["PageUp",33],PageDown:["PageDown",34]};
export function keyInput(value) {
  if(typeof value !== "string")throw new Error("invalid_key");
  const shifted=value.startsWith("Shift+"),name=shifted ? value.slice(6) : value;
  if(!Object.hasOwn(keys,name))throw new Error("invalid_key");
  const [key,code]=keys[name];
  return {key,code:name === "Space" ? "Space" : name,windowsVirtualKeyCode:code,modifiers:shifted ? 8 : 0,
    ...(["Enter","Space"].includes(name) ? {text:name === "Enter" ? "\r" : " "} : {})};
}
export function validateInteraction(action,p) {
  if(!/^c-[a-f0-9-]{36}-\d{1,4}$/u.test(p.ref || ""))throw new Error("snapshot_ref_required");
  if(action === "type" && (typeof p.text !== "string" || p.text.length>20000))throw new Error("invalid_text");
  if(action === "press_key")keyInput(p.key);
  if(action === "select_option" && (!Array.isArray(p.values) || p.values.length<1 || p.values.length>20 || p.values.some(value=>typeof value !== "string" || value.length>1000)))throw new Error("invalid_values");
  if(action === "set_checked" && typeof p.checked !== "boolean")throw new Error("invalid_checked");
}
