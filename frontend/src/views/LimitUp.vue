<script setup>
import {computed,onMounted,ref} from 'vue';
import {fmt,get,pct} from '../api/client';
import DataTable from '../components/DataTable.vue';
import MetricCard from '../components/MetricCard.vue';
import StockHistoryModal from '../components/StockHistoryModal.vue';

const runs=ref([]),selected=ref(''),data=ref(null),all=ref(false),loading=ref(false),error=ref(''),historyStock=ref(null);
const label=computed(()=>selected.value?.replaceAll('-','')||'');
async function load(){if(!label.value)return;loading.value=true;error.value='';try{data.value=await get(`/limit-up/${label.value}?candidates_only=${!all.value}&limit=${all.value?1000:100}`)}catch(e){error.value=e.message}finally{loading.value=false}}
onMounted(async()=>{try{runs.value=await get('/limit-up');selected.value=runs.value[0]?.base_date||'';await load()}catch(e){error.value=e.message}});
const columns=[
  {label:'排名',key:'ranking'},{label:'代码',key:'stock_code',action:r=>historyStock.value=r},{label:'名称',key:'stock_name'},
  {label:'触板概率',key:'touch_probability',format:pct,defaultDirection:-1},{label:'封板概率',key:'seal_probability',format:pct,defaultDirection:-1},
  {label:'综合评分',key:'score',format:v=>fmt(v,2)},{label:'基准日收盘',key:'close',format:v=>fmt(v,2)},{label:'盘中最新价',key:'current_price',format:v=>fmt(v,2)},{label:'当前涨跌幅',key:'current_change_pct',format:pct},{label:'次日涨停价',key:'limit_price',format:v=>fmt(v,2)},
  {label:'当日涨幅',key:'daily_return',format:pct},{label:'5日涨幅',key:'return_5d',format:pct},{label:'成交额比20日',key:'amount_ratio_20',format:v=>fmt(v,2)},
  {label:'换手率',key:'turnover',format:v=>`${fmt(v,2)}%`},{label:'涨幅排名改善',key:'return_rank_change',format:pct},{label:'成交额排名改善',key:'amount_rank_change',format:pct}
];
</script>
<template>
  <div class="card limit-up-intro"><div><h2>次日涨停概率 · 实验模型</h2><p>沪深主板非 ST；触板与封板分别建模，不改变现有 T+1 模型。</p></div><div class="toolbar"><select v-if="runs.length" v-model="selected" @change="load"><option v-for="run in runs" :value="run.base_date">基准日 {{run.base_date}} · Top{{run.top_n}}</option></select><label><input v-model="all" type="checkbox" @change="load">显示全部排名</label></div></div>
  <div v-if="error" class="empty negative">{{error}}</div><div v-else-if="loading" class="empty">正在加载…</div><div v-else-if="!data" class="empty">暂无涨停预测，请到任务中心执行“涨停概率预测”。</div>
  <template v-else>
    <div class="grid section"><MetricCard label="历史TopN触板率" :value="pct(data.summary.backtest.top_touch_rate)" :sub="`${data.summary.backtest.days}个滚动交易日`"/><MetricCard label="历史TopN封板率" :value="pct(data.summary.backtest.top_seal_rate)" sub="收盘仍封住涨停"/><MetricCard label="全市场触板率" :value="pct(data.summary.backtest.market_touch_rate)" sub="同口径主板非ST"/><MetricCard label="触板提升倍数" :value="data.summary.backtest.lift?`${fmt(data.summary.backtest.lift,2)}×`:'—'" sub="TopN / 全市场"/></div>
    <div class="card logic-card section"><h2>模型口径</h2><p>触板：下一交易日最高价达到按前收盘计算的 10% 涨停价；封板：下一交易日收盘仍在涨停价。回测严格使用当日前历史训练，概率经过基础发生率修正。</p><p class="hint">一字板可能无法买入；当前未接入行业、题材、新闻和资金流，结果仅用于研究观察，不构成交易建议。</p></div>
    <div class="section-heading section"><div><h2>{{all?'全部有效股票':'正式候选'}}排名</h2><span>训练 {{data.summary.training_days}} 个交易日 · {{data.summary.training_rows}} 条样本 · 股票池 {{data.summary.universe_count}} 只</span></div></div>
    <DataTable :columns="columns" :rows="data.items" default-sort="ranking"/>
    <div class="section"><h2>最近滚动回测</h2><DataTable :columns="[{label:'信号日',key:'date'},{label:'TopN触板率',key:'top_touch_rate',format:pct},{label:'TopN封板率',key:'top_seal_rate',format:pct},{label:'排除一字板后触板率',key:'tradable_touch_rate',format:pct},{label:'市场触板率',key:'market_touch_rate',format:pct}]" :rows="data.summary.backtest.rows" default-sort="date" :default-direction="-1"/></div>
    <div class="section"><div class="section-heading"><div><h2>下一交易日正式验证</h2><span v-if="data.verification">{{data.verification.base_date}} → {{data.verification.actual_trade_date}}</span></div></div>
      <div v-if="!data.verification" class="empty compact-empty">当前批次尚无下一交易日行情，等待验证。</div>
      <template v-else><div class="grid"><MetricCard label="实际触板率" :value="pct(data.verification.touch_rate)" :sub="`${data.verification.touch_count}/${data.verification.verified_count}只`"/><MetricCard label="实际封板率" :value="pct(data.verification.seal_rate)" :sub="`${data.verification.seal_count}/${data.verification.verified_count}只`"/><MetricCard label="一字板数量" :value="data.verification.one_price_count" sub="可能无法买入"/><MetricCard label="排除一字板后触板率" :value="pct(data.verification.tradable_touch_rate)" sub="候选全集口径"/></div>
      <DataTable class="section" :columns="[{label:'排名',key:'ranking'},{label:'代码',key:'stock_code'},{label:'名称',key:'stock_name'},{label:'触板概率',key:'touch_probability',format:pct},{label:'封板概率',key:'seal_probability',format:pct},{label:'涨停价',key:'limit_price',format:v=>fmt(v,2)},{label:'实际最高',key:'actual_high',format:v=>fmt(v,2)},{label:'实际收盘',key:'actual_close',format:v=>fmt(v,2)},{label:'是否触板',key:'touched',format:v=>v?'是':'否'},{label:'是否封板',key:'sealed',format:v=>v?'是':'否'},{label:'一字板',key:'one_price',format:v=>v?'是':'否'}]" :rows="data.verification.items" default-sort="ranking"/></template>
    </div>
  </template>
  <StockHistoryModal :stock="historyStock" @close="historyStock=null"/>
</template>
