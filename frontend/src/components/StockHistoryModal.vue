<script setup>
import {onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {fmt,get} from '../api/client';
import DataTable from './DataTable.vue';

const props=defineProps({stock:{type:Object,default:null}});const emit=defineEmits(['close']);
const rows=ref([]),loading=ref(false),error=ref('');
const columns=[{label:'日期',key:'trade_date'},{label:'开盘',key:'open_price',format:v=>fmt(v)},{label:'收盘',key:'close_price',format:v=>fmt(v)},{label:'最高',key:'high_price',format:v=>fmt(v)},{label:'最低',key:'low_price',format:v=>fmt(v)},{label:'涨跌幅',key:'change_pct',format:v=>v==null?'—':`${fmt(v)}%`},{label:'成交额(亿)',key:'amount',format:v=>v==null?'—':fmt(v/1e8)},{label:'换手率',key:'turnover_pct',format:v=>v==null?'—':`${fmt(v)}%`}];
async function load(stock){rows.value=[];error.value='';if(!stock)return;loading.value=true;try{const result=await get(`/stocks/${stock.stock_code}/daily?limit=120`);rows.value=result.slice().reverse()}catch(e){error.value=e.message}finally{loading.value=false}}
function onKey(event){if(event.key==='Escape'&&props.stock)emit('close')}
watch(()=>props.stock,load,{immediate:true});onMounted(()=>window.addEventListener('keydown',onKey));onBeforeUnmount(()=>window.removeEventListener('keydown',onKey));
</script>
<template><Teleport to="body"><div v-if="stock" class="modal-backdrop" @click.self="$emit('close')"><section class="stock-modal card" role="dialog" aria-modal="true" :aria-label="`${stock.stock_code} 历史行情`"><div class="detail-heading"><div><h2>{{stock.stock_code}} · {{stock.stock_name}}</h2><span class="modal-caption">最近 120 个交易日 · 数据库收盘行情</span></div><button @click="$emit('close')">关闭</button></div><div v-if="loading" class="modal-status">行情加载中…</div><div v-else-if="error" class="modal-status negative">{{error}}</div><DataTable v-else :columns="columns" :rows="rows"/></section></div></Teleport></template>
