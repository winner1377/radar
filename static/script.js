console.log('script.js loaded, version: ' + new Date().toISOString());

window.webSearch = async function() {
  console.log('webSearch called');
  try {
    var btn = document.getElementById('search-btn');
    var resultsDiv = document.getElementById('web-search-results');
    var logDiv = document.getElementById('search-log');
    
    if (!btn || !resultsDiv || !logDiv) {
      console.error('search elements not found');
      return;
    }
    
    var keywords = document.getElementById('search-keywords').value.trim();
    if (!keywords) {
      alert('Please enter keywords to search');
      return;
    }
    
    var maxLinks = document.getElementById('search-max-links').value || 5;
    var scrapeContent = document.getElementById('search-scrape').checked;
    var sendTelegram = document.getElementById('search-send').checked;
    var searchSourcesOnly = document.getElementById('search-sources-only').checked;
    
    btn.disabled = true;
    btn.innerText = 'Searching...';
    logDiv.style.display = 'block';
    logDiv.innerText = searchSourcesOnly ? 'Starting source search...\n' : 'Starting web search...\n';
    resultsDiv.style.display = 'block';
    resultsDiv.innerHTML = '';
    
    console.log('Searching with keywords:', keywords, 'Sources only:', searchSourcesOnly);
    
    var res = await fetch('/web_search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        keywords: keywords,
        max_links: parseInt(maxLinks),
        scrape_content: scrapeContent,
        send_telegram: sendTelegram,
        search_sources_only: searchSourcesOnly
      })
    });
    
    console.log('Response status:', res.status);
    var data = await res.json();
    console.log('Response data:', data);
    
    if (data.log) {
      logDiv.innerText += data.log;
    }
    
    if (data.error) {
      logDiv.innerText += 'Error: ' + data.error + '\n';
    }
    
    var searchTypeLabel = (data.search_type === 'sources') ? 'sources' : 'web';
    
    if (data.links && data.links.length > 0) {
      var countHtml = '<div class="search-results-count">Found ' + data.total_links + ' links from ' + searchTypeLabel + ' (' + data.sent_count + ' sent to Telegram)</div>';
      resultsDiv.innerHTML = countHtml;
      
      data.links.forEach(function(link, index) {
        var item = document.createElement('div');
        item.className = 'search-result-item';
        var sourceHtml = link.source ? '<div class="result-source">📡 ' + link.source + '</div>' : '';
        item.innerHTML = 
          '<div class="result-title">' + (index + 1) + '. ' + (link.title || 'No title') + '</div>' +
          sourceHtml +
          '<div class="result-url"><a href="' + link.url + '" target="_blank">' + link.url + '</a></div>';
        resultsDiv.appendChild(item);
      });
      
      logDiv.innerText += '\nDone! ' + data.total_links + ' links found from ' + searchTypeLabel + ', ' + data.sent_count + ' sent to Telegram.';
    } else {
      resultsDiv.innerHTML = '<div class="search-results-count">No links found from ' + searchTypeLabel + '.</div>';
      logDiv.innerText += '\nDone - no links found from ' + searchTypeLabel + '.';
    }
  } catch(e) {
    console.error('Error in webSearch:', e);
    var logDiv = document.getElementById('search-log');
    if (logDiv) logDiv.innerText += 'Error: ' + (e.message || 'Unknown error');
  }
  var btn = document.getElementById('search-btn');
  if (btn) {
    btn.disabled = false;
    btn.innerText = '🔍 Search & Send Links';
  }
};

window.runCycle = async function() {
  console.log('runCycle called');
  try {
    var btn = document.getElementById('run-btn');
    var log = document.getElementById('run-log');
    if (!btn || !log) {
      console.error('btn or log not found');
      return;
    }
    btn.disabled = true;
    btn.innerText = 'Running...';
    log.style.display = 'block';
    log.innerText = 'Starting cycle...\n';

    console.log('Fetching /run...');
    var res = await fetch('/run', { method: 'POST' });
    console.log('Response status:', res.status);
    var data = await res.json();
    console.log('Response data:', data);
    if (data && data.log !== undefined) {
      log.innerText = log.innerText + String(data.log) + '\nDone - ' + (data.sent || 0) + ' articles sent.';
    } else {
      log.innerText = log.innerText + 'Done - 0 articles sent.';
    }
  } catch(e) {
    console.error('Error in runCycle:', e);
    var log = document.getElementById('run-log');
    if (log) log.innerText = log.innerText + 'Error: ' + (e.message || 'Unknown error');
  }
  var btn = document.getElementById('run-btn');
  if (btn) {
    btn.disabled = false;
    btn.innerText = 'Run Now';
  }
};

console.log('window.runCycle defined:', typeof window.runCycle);