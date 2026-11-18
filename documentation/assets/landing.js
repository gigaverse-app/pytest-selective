document.querySelectorAll('.lp [data-copy]').forEach(function (button) { if (!navigator.clipboard) return;
button.hidden = false;
button.addEventListener('click', async function () { const target = document.getElementById(button.dataset.copy);
try { await navigator.clipboard.writeText(target.textContent);
button.nextElementSibling.textContent = ' Copied';
} catch { button.nextElementSibling.textContent = ' Select the text above to copy it.';
} });
});