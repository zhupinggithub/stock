<script setup>defineProps({label:String,value:[String,Number],sub:String,tone:String})</script>
<template><article class="card metric"><label>{{label}}</label><strong :class="tone">{{value}}</strong><small>{{sub}}</small></article></template>
