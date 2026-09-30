/** E2E wire-shape checks only; real ACL/CAS and SQL acceptance are tested separately. */
const shape = (v, keys) => v !== null && typeof v === 'object' && !Array.isArray(v)
  && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const nonblank = v => typeof v === 'string' && v.trim().length > 0;
const id = v => nonblank(v) && Array.from(v).length <= 200;
const integer = (v, min = 0) => Number.isSafeInteger(v) && v >= min;
const canonical = v => Array.isArray(v) ? `[${v.map(canonical).join(',')}]` : v && typeof v === 'object'
  ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}` : JSON.stringify(v);
const equal = (a,b) => canonical(a) === canonical(b);
const span = q => integer(q.start) && integer(q.end,1) && q.end > q.start && nonblank(q.quote);
function targetQuote(q, version) {
  if (!q || !span(q)) return false;
  if (['description','requirement'].includes(q.field)) return shape(q,['field','requirement_index','start','end','quote'])
    && (q.field === 'description' ? q.requirement_index === null : integer(q.requirement_index));
  if (['paper_title','paper_abstract'].includes(q.field)) return version >= 2
    && shape(q,['field','paper_index','start','end','quote']) && integer(q.paper_index);
  if (['lab_heading','lab_text'].includes(q.field)) return version === 3
    && shape(q,['field','page_index','section_index','start','end','quote']) && integer(q.page_index) && integer(q.section_index);
  return false;
}
function changeValid(c, kind, version) {
  if (!shape(c,['section_id','block_id','line_id','field','before','after','reason','target_evidence','source_evidence','check'])
    || ![c.section_id,c.block_id,c.line_id].every(v => v === null || id(v))
    || !(c.reason === null || typeof c.reason === 'string') || !Array.isArray(c.target_evidence) || !Array.isArray(c.source_evidence)
    || (c.block_id !== null && c.section_id === null) || (c.line_id !== null && c.block_id === null)
    || (kind !== 'manual' && equal(c.before,c.after))) return false;
  if (kind === 'target_order' && c.field !== 'order' || kind === 'ai_rewrite' && c.field === 'included' || kind === 'plan' && c.field === 'order') return false;
  if (['manual','target_order'].includes(kind) && (c.reason !== null || c.target_evidence.length || c.source_evidence.length || c.check !== null)) return false;
  if (c.field === 'text') { if (c.line_id === null || typeof c.before !== 'string' || typeof c.after !== 'string') return false; }
  else if (c.field === 'included') { if (c.section_id === null || typeof c.before !== 'boolean' || typeof c.after !== 'boolean') return false; }
  else if (c.field === 'order') {
    if (c.line_id !== null || ![c.before,c.after].every(v => Array.isArray(v) && v.every(id) && new Set(v).size === v.length)) return false;
  } else return false;
  if (!c.target_evidence.every(q => targetQuote(q,version))
    || !c.source_evidence.every(q => shape(q,['unit_id','start','end','quote']) && id(q.unit_id) && span(q))) return false;
  if (c.check !== null) {
    const k=c.check;
    if (c.field !== 'text' || !['ai_rewrite','plan'].includes(kind)
      || !shape(k,['version','pipeline_version','request_id','document_signature','original','evidence'])
      || !['version','pipeline_version','request_id','document_signature'].every(f => nonblank(k[f]))
      || !/^v1:sha256:[a-f0-9]{64}$/.test(k.document_signature) || typeof k.original !== 'string'
      || !shape(k.evidence,['kind','id','revision']) || k.evidence.kind !== 'experience' || !id(k.evidence.id) || !integer(k.evidence.revision,1)) return false;
  }
  return true;
}
export function validStubTargetResumeProvenance(doc, value) {
  if (value === null) return true;
  if (!shape(value,['version','document_id','opportunity_id','base','events']) || ![1,2,3].includes(value.version)
    || value.version === 2 && doc.target_snapshot?.context_version !== 3
    || value.version === 3 && doc.target_snapshot?.context_version !== 4
    || !id(value.document_id) || !id(value.opportunity_id) || value.document_id !== doc.id || value.opportunity_id !== doc.opportunity_id
    || !equal(value.base,doc.base) || !shape(value.base,['master_id','master_revision','profile_signature','source_signature','target_signature'])
    || !['master_id','profile_signature','source_signature','target_signature'].every(k => nonblank(value.base[k])) || !integer(value.base.master_revision,1)
    || !Array.isArray(value.events) || !value.events.length || value.events.length > 512
    || Buffer.byteLength(JSON.stringify(value),'utf8') > 262144) return false;
  const ids=new Set();
  return value.events.every(e => {
    if (!shape(e,['id','kind','changes']) || !id(e.id) || ids.has(e.id) || !['manual','ai_rewrite','plan','target_order'].includes(e.kind)
      || !Array.isArray(e.changes) || !e.changes.length || e.changes.length > 1024) return false;
    ids.add(e.id); return e.changes.every(c => changeValid(c,e.kind,value.version));
  });
}
