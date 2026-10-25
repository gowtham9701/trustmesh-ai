from __future__ import annotations
import os, requests, streamlit as st
from auth import require_public_demo_password
API=os.getenv('OPSPILOT_API_URL','http://localhost:8000').rstrip('/')
API_TOKEN=os.getenv('OPSPILOT_API_TOKEN','')
AUTH={'Authorization':f'Bearer {API_TOKEN}'} if API_TOKEN else {}
st.set_page_config(page_title='TrustMesh AI', page_icon='🕸️', layout='wide')
if not require_public_demo_password():
    st.stop()
st.title('🕸️ TrustMesh AI')
st.caption('Local-first, evidence-grounded incident investigation — transparent by design.')

def call(method,path,**kwargs):
    headers=dict(kwargs.pop('headers',{}))
    headers.update(AUTH)
    r=requests.request(method,API+path,timeout=60,headers=headers,**kwargs); r.raise_for_status(); return r.json()

@st.cache_data(ttl=30,show_spinner=False)
def suggested_questions(limit,signature):
    del signature  # hashed into the cache key so results stay scoped to the indexed documents
    r=requests.get(API+'/api/v1/questions/suggested',params={'limit':limit},headers=dict(AUTH),timeout=60)
    r.raise_for_status(); return r.json()

documents,api_error=[],None
try:
    documents=call('GET','/api/v1/documents')
except requests.RequestException as e: api_error=str(e)
signature=tuple((d['id'],d['version']) for d in documents)
with st.sidebar:
    st.header('Workspace')
    try:
        h=call('GET','/health'); st.success('API online · '+h['retrieval'])
        metadata=call('GET','/api/v1/ai/metadata')
        st.caption(f"Workflow: {metadata['workflow']['engine']} · Tracing: {metadata['tracing']['provider']}")
    except requests.RequestException as e: st.error(f'API unavailable: {e}')
    st.info('No external model is required. Hosted demo data is temporary and may reset; findings are suggestions, not remediation.')
    st.subheader('Indexed documents')
    if api_error: st.error(f'Unable to load documents: {api_error}')
    for d in documents: st.write(f"• {d['filename']} (v{d['version']}, {d['chunks']} chunks)")

st.subheader('1. Add incident evidence')
file=st.file_uploader(
    'Upload Markdown, text, or JSON',
    type=['md','txt','json'],
    help='UTF-8 .md, .txt, or valid .json files only; default maximum is 10 MiB.',
)
if file and st.button('Index document'):
    try: st.success(call('POST','/api/v1/ingest',files={'file':(file.name,file.getvalue(),file.type)})['filename']); st.rerun()
    except requests.HTTPError as e: st.error(e.response.text)
st.subheader('2. Ask an investigation question')
try: suggestions=suggested_questions(5,signature)['items']
except requests.RequestException: suggestions=[]
labels=[item['question'] for item in suggestions]
if st.session_state.get('suggested_question') not in labels: st.session_state['suggested_question']=''
choice=st.selectbox(
    'Suggested from your evidence',['']+labels,key='suggested_question',
    format_func=lambda value: value or 'Select a suggestion, or write your own question below',
)
if choice and st.session_state.get('applied_question')!=choice:
    st.session_state['question']=choice
    st.session_state['applied_question']=choice
if choice:
    source=next((item for item in suggestions if item['question']==choice),None)
    if source: st.caption(f"Grounded in {source['source_filename']} · {source['source_chunk_id']} · matched {', '.join(source['signals'])}")
elif not labels: st.caption('No suggestions yet — index a document in step 1 and questions are generated from its content.')
question=st.text_area('Question',height=90,key='question',placeholder='What changed, what broke, or what should be checked next?')
if st.button('Investigate',type='primary'):
    if not question.strip(): st.error('Pick a suggested question or write one before investigating.')
    else:
        try: st.session_state.result=call('POST','/api/v1/investigate',json={'question':question})
        except requests.HTTPError as e: st.error(e.response.text)
r=st.session_state.get('result')
if r:
    st.divider(); st.subheader('Finding')
    c1,c2,c3=st.columns(3); c1.metric('Confidence',f"{r['confidence']:.0%}"); c2.metric('Verification',r['verification']['status']); c3.metric('Evidence',len(r['evidence']))
    st.caption(f"Workflow: {r['workflow_engine']} · Retrieval: {r['retrieval_mode']} · Reranker: {r['reranker']}")
    if r['insufficient_evidence']: st.warning(r['answer'])
    elif r['deadlock']: st.error(r['answer'])
    else: st.markdown(r['answer'])
    st.subheader('Evidence citations')
    for e in r['evidence']:
        with st.expander(f"{e['filename']} · {e['chunk_id']} · score {e['score']:.2f}"): st.write(e['quote'])
    st.subheader('Agent opinions')
    for o in r['agent_opinions']: st.markdown(f"**{o['agent']}** · {o['confidence']:.0%}\n\n{o['conclusion']}\n\n_{o['rationale']}_")
    st.subheader('Verification'); st.write(r['verification']['explanation'])
    if r['verification'].get('claims'):
        st.subheader('Claim-level checks')
        st.dataframe(r['verification']['claims'], use_container_width=True, hide_index=True)
        st.caption(f"Citation coverage: {r['verification']['citation_coverage']:.0%} · Contradictions: {r['verification']['contradiction_count']}")
    st.subheader('Recommended actions'); [st.write(f'• {a}') for a in r['recommended_actions']]
    st.subheader('Human approval workflow')
    with st.form('approval_request'):
        approval_action=st.text_input('Proposed change (not executed)',placeholder='e.g. Roll back release 8.1 after service-owner approval')
        approval_rationale=st.text_area('Evidence and rationale',placeholder='Reference the incident evidence and explain why review is needed.')
        request_approval=st.form_submit_button('Request human approval')
    if request_approval:
        try:
            approval=call('POST','/api/v1/approvals',json={
                'investigation_id':r['investigation_id'],
                'action':approval_action,
                'rationale':approval_rationale,
            })
            st.success(f"Approval request {approval['id']} is {approval['status']}. No system change was executed.")
        except requests.HTTPError as e: st.error(e.response.text)
        except requests.RequestException as e: st.error(f'Could not create approval request: {e}')
    try:
        pending=call('GET','/api/v1/approvals')['items']
        if pending:
            st.subheader('Approval queue')
            for approval in pending:
                st.write(f"{approval['status'].upper()} · {approval['action']} · {approval['rationale']}")
                if approval['status']=='pending':
                    decision=st.selectbox('Decision', ['approved','rejected'], key=f"decision-{approval['id']}")
                    decision_comment=st.text_input('Decision note', key=f"note-{approval['id']}")
                    if st.button('Record decision', key=f"submit-{approval['id']}"):
                        try:
                            call('POST',f"/api/v1/approvals/{approval['id']}/decision",json={
                                'decision':decision,'comment':decision_comment,
                            })
                            st.success('Decision recorded. This does not execute the proposed change.')
                        except requests.HTTPError as e: st.error(e.response.text)
    except requests.RequestException as e: st.error(f'Unable to load approval queue: {e}')
    st.subheader('Was this useful?')
    rating=st.selectbox('Feedback', ['helpful','mixed','not_helpful'], key='rating'); comment=st.text_input('Optional comment',key='comment')
    if st.button('Submit feedback'):
        call('POST','/api/v1/feedback',json={'investigation_id':r['investigation_id'],'rating':rating,'comment':comment}); st.success('Feedback recorded')
