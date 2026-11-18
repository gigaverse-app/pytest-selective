---
title: pytest-selective
description: Run the Python tests affected by your edit.
hide:
  - navigation
  - toc
---

<div class="lp py">
<header><div><p class="brand">pytest-selective</p><h1>Test what your change touches.</h1><p>Get feedback on your edit without running every Python test. pytest-selective finds the tests that depend on the code you changed.</p><a class="cta" href="#try-it">Try it on a local edit ↓</a><p class="sub">Free · Apache 2.0 · Works with your existing pytest suite</p></div>
<aside><small>CI runner time · MongoDB test change</small><strong>94%<span style="font-size:.32em;letter-spacing:-.03em"> less</span></strong><p>Full workflow · 1,602 seconds</p><div class="bar"></div><p>Selected workflow · 93 seconds</p><div class="bar short" style="width:5.8%"></div><a href="https://pytest-selective.readthedocs.io/en/latest/ecosystem/">See how the gate fell from 5m22s to 54s ↗</a></aside></header>
<section class="setup" id="try-it"><h2>Start with one function.</h2><p>In a Git project with a passing pytest suite, install the plugin and commit the dependency change.</p><pre id="first-command">uv add --dev pytest-selective</pre><button type="button" hidden data-copy="first-command">Copy install command</button><span role="status" aria-live="polite"></span><p>Edit an application function, then run:</p><pre>uv run pytest --selective</pre><p>The summary shows which tests your edit selected. Use <code>uv run pytest --no-selective</code> for a full run.</p><p><a href="https://pytest-selective.readthedocs.io/en/latest/docs/tutorial/">Follow the local tutorial →</a> · <a href="https://pytest-selective.readthedocs.io/en/latest/agent-setup/">Set up CI with your coding agent</a></p></section>
<section><h2>From a code edit to a test plan.</h2><div class="grid"><article><h3>Follow indirect imports</h3><p>Edit a pricing helper and select the checkout tests that reach it through other modules.</p></article><article><h3>See why a test ran</h3><p>Inspect the selection report. Declare runtime inputs such as files a test opens on disk.</p></article><article><h3>Skip service startup</h3><p>Plan before pytest collection in CI so unrelated changes can skip the whole job. Uncertain changes run the full suite.</p></article></div></section>
<footer><a href="https://github.com/gigaverse-app/pytest-selective">GitHub</a> · <a href="https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/adoption-checklist/">Adoption guide</a> · <a href="https://pytest-selective.readthedocs.io/en/latest/docs/actions/">Actions reference</a></footer></div>
