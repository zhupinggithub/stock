<script setup>
import {onMounted,onUnmounted,ref} from 'vue';
import {get,post,put} from '../api/client';
import DataTable from '../components/DataTable.vue';
const props=defineProps({user:{type:Object,required:true}}),can=p=>props.user.permissions?.includes(p);
const taskPermissions={collect:'task:collect',predict:'task:predict',verify:'task:verify',intraday:'task:intraday',pipeline:'task:pipeline'};
const labels={collect:'拉取收盘增量',predict:'执行预测',verify:'执行正式验证',intraday:'获取盘中观察',pipeline:'完整每日流水线'};
const help={collect:'拉取指定交易日行情并同步数据库，唯一键保证重复拉取不会产生重复记录。',predict:'根据最新日线生成两个模型的候选；同一基准日重复执行会更新结果。',verify:'用已入库的后续行情验证历史预测；行情不足时保持等待验证。',intraday:'获取一次实时快照，不修改历史日线、正式预测或验证结果。',pipeline:'依次完成收盘增量、验证上一期并生成两个模型的下一期预测。'};
const today=new Date().toLocaleDateString('en-CA'),jobs=ref([]),selected=ref(),message=ref(''),timer=ref();
const dataDir=ref('data'),source=ref('sina'),top=ref(30),tradeDate=ref(today);
const schedule=ref({enabled:false,run_time:'15:20',weekdays:[1,2,3,4,5],data_dir:'data',data_source:'sina',top_n:30}),scheduleMessage=ref('');
const dayNames={1:'周一',2:'周二',3:'周三',4:'周四',5:'周五',6:'周六',7:'周日'};
async function refresh(){jobs.value=await get('/tasks?limit=30');if(selected.value)selected.value=await get(`/tasks/${selected.value.id}`);const active=jobs.value.some(x=>['pending','running'].includes(x.status));if(active&&!timer.value)timer.value=setInterval(refresh,2000);if(!active&&timer.value){clearInterval(timer.value);timer.value=null}}
async function loadSchedule(){schedule.value=await get('/tasks/schedule');schedule.value.weekdays=String(schedule.value.weekdays).split(',').map(Number);schedule.value.run_time=String(schedule.value.run_time).slice(0,5)}
function toggleDay(day){schedule.value.weekdays=schedule.value.weekdays.includes(day)?schedule.value.weekdays.filter(x=>x!==day):[...schedule.value.weekdays,day].sort()}
async function saveSchedule(){scheduleMessage.value='';if(!schedule.value.weekdays.length)return scheduleMessage.value='请至少选择一个执行日';try{schedule.value=await put('/tasks/schedule',{enabled:schedule.value.enabled,run_time:schedule.value.run_time,weekdays:schedule.value.weekdays,data_dir:schedule.value.data_dir,source:schedule.value.data_source,top:Number(schedule.value.top_n)});schedule.value.weekdays=String(schedule.value.weekdays).split(',').map(Number);scheduleMessage.value='定时配置已保存'}catch(e){scheduleMessage.value=e.message}}
async function submit(job_type){message.value='';try{const body=await post('/tasks',{job_type,data_dir:dataDir.value,source:source.value,top:Number(top.value),trade_date:job_type==='collect'?tradeDate.value:null});message.value=`任务 #${body.id} 已提交`;await refresh()}catch(e){message.value=e.message}}
async function show(row){selected.value=selected.value?.id===row.id?null:await get(`/tasks/${row.id}`)}
function onKey(event){if(event.key==='Escape'&&selected.value)selected.value=null}
const columns=[{label:'任务ID',key:'id',format:v=>`#${v}`,action:show},{label:'任务',key:'job_type',format:v=>labels[v]||v},{label:'状态',key:'status'},{label:'进度',key:'progress',format:v=>`${v}%`},{label:'触发方式',key:'trigger_type'},{label:'创建人',key:'created_by_username',format:v=>v||'系统'},{label:'创建时间',key:'created_at'},{label:'结束时间',key:'finished_at'}];
onMounted(()=>{window.addEventListener('keydown',onKey);return Promise.all([refresh(),can('schedule:view')?loadSchedule():Promise.resolve()])});onUnmounted(()=>{window.removeEventListener('keydown',onKey);if(timer.value)clearInterval(timer.value)});
</script>
<template>
  <div v-if="can('schedule:view')" class="card schedule-panel">
    <div class="detail-heading"><div><h2>自动任务</h2><span class="modal-caption">后端服务运行期间，按设定时间自动执行每日完整流水线</span></div><label class="switch"><input v-model="schedule.enabled" type="checkbox" :disabled="!can('schedule:update')"><span>{{schedule.enabled?'已启用':'已停用'}}</span></label></div>
    <div class="schedule-grid"><label>执行时间<input v-model="schedule.run_time" type="time" :disabled="!can('schedule:update')"></label><label>数据目录<input v-model="schedule.data_dir" :disabled="!can('schedule:update')"></label><label>行情来源<select v-model="schedule.data_source" :disabled="!can('schedule:update')"><option value="sina">新浪</option><option value="eastmoney">东方财富</option><option value="auto">自动切换</option></select></label><label>候选数量<input v-model.number="schedule.top_n" type="number" min="1" max="500" :disabled="!can('schedule:update')"></label></div>
    <div class="weekday-row"><span>执行日</span><button v-for="(name,day) in dayNames" :key="day" :disabled="!can('schedule:update')" :class="{active:schedule.weekdays.includes(Number(day))}" @click="toggleDay(Number(day))">{{name}}</button></div>
    <div class="schedule-footer"><div><span>下次执行：{{schedule.next_run_at||'停用后不执行'}}</span><span>上次触发：{{schedule.last_trigger_date||'尚未执行'}} <template v-if="schedule.last_job_id">· 任务 #{{schedule.last_job_id}}</template></span></div><button v-if="can('schedule:update')" @click="saveSchedule">保存定时配置</button></div><p v-if="scheduleMessage" class="notice">{{scheduleMessage}}</p>
  </div>
  <div class="card task-panel"><h2>新建任务</h2><p class="hint">任务在后台执行，同一时间只允许一个任务运行。</p>
    <div class="task-config"><label>数据目录<input v-model="dataDir"></label><label>行情来源<select v-model="source"><option value="sina">新浪</option><option value="eastmoney">东方财富</option><option value="auto">自动切换</option></select></label><label>候选数量<input v-model.number="top" type="number" min="1" max="500"></label><label>收盘行情日期<input v-model="tradeDate" type="date" :max="today"><small>历史日期可用于补拉。</small></label></div>
    <div class="task-actions"><article v-for="(label,key) in labels" v-show="can(taskPermissions[key])" :key="key"><div><h3>{{label}}</h3></div><p>{{help[key]}}</p><button @click="submit(key)">执行{{label}}</button></article></div><p v-if="message" class="notice">{{message}}</p>
  </div>
  <div class="section"><div class="section-heading"><h2>最近任务</h2><span>点击任务 ID 查看执行详情</span></div><DataTable :columns="columns" :rows="jobs"/></div>
  <Teleport to="body"><div v-if="selected" class="modal-backdrop" @click.self="selected=null"><section class="task-detail-modal stock-modal card" role="dialog" aria-modal="true" :aria-label="`任务 ${selected.id} 执行详情`"><div class="detail-heading"><div><h2>任务 #{{selected.id}} · {{labels[selected.job_type]}}</h2><span class="modal-caption">{{selected.trigger_type||'manual'}} · {{selected.created_by_username||'系统'}}</span></div><button @click="selected=null">关闭</button></div><div class="progress"><i :style="{width:`${selected.progress}%`}"></i></div><p>状态：<b>{{selected.status}}</b>　进度：{{selected.progress}}%</p><p v-if="selected.error_message" class="negative">{{selected.error_message}}</p><pre>{{selected.log_text||'等待日志…'}}</pre></section></div></Teleport>
</template>
