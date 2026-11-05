import { extractArticle } from '../scripts/plan.mjs';

const html = `<html><head><style>.x{color:red}</style></head><body>
<div id="js_content"><p>这是一段测试正文，长度足够用来测试抽取逻辑是否正常工作。</p>
<p>第二段，再补充一些内容，让长度超过一百二十个字符，确保能通过最小长度校验，不至于被当成空页面。</p></div>
<script>var a = 1;</script></body></html>`;

const out = extractArticle(html);
console.log('长度:', out.length);
console.log('内容:', out.slice(0, 80).replace(/\n/g, ' / '));
console.log('没有脚本残留:', !out.includes('var a'));
