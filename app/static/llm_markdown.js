/* Local, dependency-free Markdown renderer for streaming LLM output.
   Model text is escaped before supported Markdown elements are added. */
window.BmcMarkdown=(()=>{
  const reasoningStart='[[BMC_REASONING_START]]',reasoningEnd='[[BMC_REASONING_END]]';
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const inline=source=>{const codes=[],images=[];const imageMarked=String(source??'').replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+|data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+)\)(?:\{width=((?:25|50|75|100)%|(?:[1-9]\d{1,2})px)\})?/g,(_,alt,src,size)=>`@@BMC_IMAGE_${images.push({alt,src,size})-1}@@`);let value=escape(imageMarked).replace(/`([^`]+)`/g,(_,code)=>`@@BMC_CODE_${codes.push(code)-1}@@`);value=value.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>').replace(/\*([^*]+)\*/g,'<em>$1</em>').replace(/(^|[^\w])_([^_]+)_/g,'$1<em>$2</em>');value=value.replace(/@@BMC_IMAGE_(\d+)@@/g,(_,index)=>{const image=images[Number(index)];if(!image)return '';const size=/^(?:25|50|75|100)%$|^(?:[1-9]\d{1,2})px$/.test(image.size||'')?image.size:'';const style=size?` style="width:${size};max-width:100%;height:auto"`:'';return `<img src="${escape(image.src)}" alt="${escape(image.alt)}" loading="lazy" decoding="async"${style} data-image-width="${escape(size)}">`});return value.replace(/@@BMC_CODE_(\d+)@@/g,(_,index)=>`<code>${codes[Number(index)]}</code>`)};
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(cell=>cell.trim().replace(/\\\|/g,'|'));
  const divider=line=>line.includes('|')&&cells(line).length>0&&cells(line).every(cell=>/^:?-{3,}:?$/.test(cell.replace(/\s/g,'')));
  function render(source){
    const lines=String(source??'').replace(/\r\n?/g,'\n').split('\n'),html=[];let paragraph=[],listType='',listItems=[],quote=[],inFence=false,code=[];
    const flushParagraph=()=>{if(paragraph.length){html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);paragraph=[]}};
    const flushList=()=>{if(listItems.length){html.push(`<${listType}>${listItems.map(item=>`<li>${inline(item)}</li>`).join('')}</${listType}>`);listItems=[];listType=''}};
    const flushQuote=()=>{if(quote.length){html.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`);quote=[]}};
    const flush=()=>{flushParagraph();flushList();flushQuote()};
    for(let index=0;index<lines.length;index+=1){const line=lines[index];
      if(/^\s*```/.test(line)){if(inFence){html.push(`<pre><code>${escape(code.join('\n'))}</code></pre>`);code=[];inFence=false}else{flush();inFence=true}continue}
      if(inFence){code.push(line);continue}
      if(line.includes('|')&&index+1<lines.length&&divider(lines[index+1])){flush();const headers=cells(line),alignments=cells(lines[index+1]);const rows=[];index+=2;while(index<lines.length&&lines[index].trim()&&lines[index].includes('|')){rows.push(cells(lines[index]));index+=1}index-=1;const align=(value)=>value.startsWith(':')&&value.endsWith(':')?'center':value.endsWith(':')?'right':'left';html.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map((cell,i)=>`<th style="text-align:${align(alignments[i]||'')}">${inline(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${headers.map((_,i)=>`<td style="text-align:${align(alignments[i]||'')}">${inline(row[i]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);continue}
      if(!line.trim()){flush();continue}const heading=line.match(/^(#{1,6})\s+(.+)$/);if(heading){flush();html.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);continue}if(/^\s*((---+)|(\*\*\*+)|(___+))\s*$/.test(line)){flush();html.push('<hr>');continue}const block=line.match(/^>\s?(.*)$/);if(block){flushParagraph();flushList();quote.push(block[1]);continue}const list=line.match(/^\s*([-+*])\s+(.+)$/),ordered=line.match(/^\s*\d+[.)]\s+(.+)$/);if(list||ordered){flushParagraph();flushQuote();const nextType=ordered?'ol':'ul';if(listType&&listType!==nextType)flushList();listType=nextType;listItems.push((list||ordered)[2]||ordered[1]);continue}flushList();flushQuote();paragraph.push(line)}
    if(inFence)html.push(`<pre><code>${escape(code.join('\n'))}</code></pre>`);else flush();return html.join('')||'<p></p>'
  }
  function renderAssistant(source,streaming=false){
    const value=String(source??''),start=value.indexOf(reasoningStart);
    if(start<0)return render(value);
    const end=value.indexOf(reasoningEnd,start+reasoningStart.length);
    const reasoning=value.slice(start+reasoningStart.length,end<0?value.length:end).trim();
    const answer=(end<0?'':value.slice(end+reasoningEnd.length)).trim();
    const open=streaming&&end<0?' open':'';
    const summary=end<0?'正在思考…':'思考过程（点击展开）';
    const reasoningHtml=reasoning?render(reasoning):'<p>模型正在整理思路…</p>';
    const answerHtml=answer?`<div class="assistant-final">${render(answer)}</div>`:(end<0?'':'<p class="assistant-empty-final">模型未返回最终答案。</p>');
    return `<details class="assistant-reasoning"${open}><summary>${summary}</summary><div class="assistant-reasoning-body">${reasoningHtml}</div></details>${answerHtml}`;
  }
  const normalizeImages=element=>{if(window.BmcEditorMedia&&typeof window.BmcEditorMedia.normalizeRenderedImages==='function')window.BmcEditorMedia.normalizeRenderedImages(element)};
  return{
    render,
    renderTo(element,source){element.innerHTML=render(source);normalizeImages(element)},
    renderAssistant,
    renderAssistantTo(element,source,options={}){element.innerHTML=renderAssistant(source,Boolean(options.streaming));normalizeImages(element)}
  }
})();
