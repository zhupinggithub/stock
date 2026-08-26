<script setup>
import {computed,onMounted,ref} from 'vue';
import {get,fmt,pct} from '../api/client';
import DataTable from '../components/DataTable.vue';import StockHistoryModal from '../components/StockHistoryModal.vue';
const modelNames={multi_factor_rank:'次日方向模型',tradeable_t1_open:'T+1可交易模型'},runs=ref([]),activeModel=ref('multi_factor_rank'),selected=ref({}),data=ref({candidates:[],factors:[]}),showLogic=ref(false),historyStock=ref(null);
const modelRuns=computed(()=>runs.value.filter(r=>r.model_code===activeModel.value)),isTradeable=computed(()=>activeModel.value==='tradeable_t1_open');
async function load(){const id=selected.value[activeModel.value];data.value=id?await get(`/predictions/${id}/candidates`):{candidates:[],factors:[]}}
async function switchModel(code){activeModel.value=code;showLogic.value=false;await load()}
onMounted(async()=>{runs.value=await get('/predictions');for(const code of Object.keys(modelNames))selected.value[code]=runs.value.find(r=>r.model_code===code)?.id;await load()});
const rankChange=v=>v==null?'—':v>0?`↑${v}`:v<0?`↓${Math.abs(v)}`:'持平';
const candidates=[
 {label:'排名',key:'ranking'},{label:'代码',key:'stock_code',action:r=>historyStock.value=r},{label:'市场',key:'market'},{label:'名称',key:'stock_name'},
 {label:'连续入选',key:'consecutive_count',format:v=>`${v}期`},{label:'近5期',key:'recent_5_count',format:(v,r)=>`${v}/${r.recent_5_periods}`},{label:'近10期',key:'recent_10_count',format:(v,r)=>`${v}/${r.recent_10_periods}`},
 {label:'上期排名',key:'previous_ranking',format:v=>v==null?'—':`第${v}名`},{label:'排名变化',key:'ranking_change',format:rankChange},
 {label:'评分',key:'score',format:v=>fmt(v,3)},{label:'上涨概率',key:'up_probability',format:pct},{label:'概率变化',key:'probability_change',format:v=>v==null?'—':`${v>=0?'+':''}${pct(v)}`},
 {label:'预计收益',key:'expected_return',format:pct},{label:'目标价',key:'target_price',format:v=>fmt(v,2)},{label:'90%收益区间',key:'return_low_90',format:(v,r)=>v==null?'—':`${pct(v)} ~ ${pct(r.return_high_90)}`},
 {label:'90%价格区间',key:'price_low_90',format:(v,r)=>v==null?'—':`${fmt(v,2)} ~ ${fmt(r.price_high_90,2)}`},{label:'置信度',key:'prediction_confidence',format:pct},{label:'信号日收盘',key:'base_close'}
];
const factors=[{label:'因子',key:'factor_name'},{label:'代码',key:'factor_code'},{label:'权重',key:'model_weight',format:pct},{label:'平均IC',key:'mean_ic',format:v=>fmt(v,4)},{label:'正IC比例',key:'positive_ic_rate',format:pct}];
</script>
<template>
 <div class="model-tabs"><button v-for="(name,code) in modelNames" :key="code" :class="{active:activeModel===code}" @click="switchModel(code)">{{name}}</button></div>
 <div class="prediction-toolbar"><select v-if="modelRuns.length" v-model="selected[activeModel]" @change="load"><option v-for="r in modelRuns" :key="r.id" :value="r.id">预测基准日 {{r.base_date}} · {{r.model_version}}</option></select><span v-else>该模型暂无预测批次</span><button @click="showLogic=!showLogic">{{showLogic?'收起选股逻辑':'查看选股逻辑'}}</button></div>
 <div class="experimental-note"><template v-if="isTradeable"><b>T+1可交易口径：</b>下一交易日开盘模拟买入，再下一交易日开盘模拟卖出；入场价产生前不展示目标价格。</template><template v-else><b>次日方向口径：</b>信号日收盘至下一交易日收盘，不等同于收盘后下单的实际交易收益。</template></div>
 <div v-if="showLogic" class="card logic-card"><div class="detail-heading"><h2>{{modelNames[activeModel]}}计算逻辑</h2><button @click="showLogic=false">收起</button></div><ol><li>两个模型使用相同九个行情因子，但根据各自收益目标独立计算 Rank IC 和权重。</li><li v-if="isTradeable">训练目标为下一交易日开盘买入、再下一交易日开盘卖出的收益。</li><li v-else>训练目标为信号日收盘至下一交易日收盘的收益。</li><li>过滤 ST、历史不足和流动性不足的股票，再按综合评分选出 TopN。</li><li>连续入选按同一模型最近预测批次统计，只用于观察信号稳定性，不会额外增加模型分数或上涨概率。</li></ol></div>
 <div class="section"><h2>{{modelNames[activeModel]}}候选排名</h2><p class="hint">“连续入选”包含本期；排名变化 ↑ 表示排名提升。近5/10期不足时仍按现有历史批次数统计。</p><DataTable :columns="candidates" :rows="data.candidates"/></div>
 <div class="section"><h2>{{modelNames[activeModel]}}因子权重</h2><DataTable :columns="factors" :rows="data.factors"/></div><StockHistoryModal :stock="historyStock" @close="historyStock=null"/>
</template>
