<script lang="ts">
	import '../app.css';
	import ThemeProvider from '$lib/themes/ThemeProvider.svelte';
	let { children } = $props();
</script>

<ThemeProvider>
	<div class="h-screen min-h-dvh w-screen overflow-hidden bg-canvas text-text-primary" data-testid="app-shell">
		{@render children()}
	</div>
</ThemeProvider>
