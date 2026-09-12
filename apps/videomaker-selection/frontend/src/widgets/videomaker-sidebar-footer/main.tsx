import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { UserPlus } from 'lucide-react';
import '../../styles/sidebar-widget.css';
const APP_ID='videomaker-selection';const WIDGET_ID='videomaker-sidebar-footer';const LABEL='Nuovo candidato';
function openNew(){window.parent?.postMessage({type:'maverick.widget.open-app',app_id:APP_ID,params:{app_page:'new',new_candidate:true,request_id:`candidate-${Date.now()}`}},'*');if(window.matchMedia('(max-width:979px)').matches)window.parent?.postMessage({type:'maverick.shell.sidebar.close'},'*')}
function state(){window.parent?.postMessage({type:'maverick.widget.primary-action.state',owner_app_id:APP_ID,widget_id:WIDGET_ID,available:true,label:LABEL,preferred_surface:'sidebar'},'*')}
function Footer(){useEffect(()=>{state();const handler=(event:MessageEvent)=>{if(event.origin!==location.origin||!event.data||typeof event.data!=='object')return;const data=event.data as {type?:string;owner_app_id?:string;widget_id?:string};if(data.owner_app_id!==APP_ID||data.widget_id!==WIDGET_ID)return;if(data.type==='maverick.widget.primary-action.query')state();if(data.type==='maverick.widget.primary-action.invoke')openNew()};window.addEventListener('message',handler);return()=>window.removeEventListener('message',handler)},[]);return <main className="vm-sidebar-footer"><button onClick={openNew} type="button"><UserPlus size={16}/><span>{LABEL}</span></button></main>}
createRoot(document.getElementById('videomaker-sidebar-footer-root') as HTMLElement).render(<Footer/>);
