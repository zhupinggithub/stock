import {ref} from 'vue'
export const currentView=ref(location.hash.slice(1)||'dashboard')
addEventListener('hashchange',()=>currentView.value=location.hash.slice(1)||'dashboard')
export function navigate(view){location.hash=view}
