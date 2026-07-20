<script lang="ts">
	import { getOllamaVersion } from '$lib/apis/ollama';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { WEBUI_BUILD_HASH, WEBUI_VERSION } from '$lib/constants';
	import { WEBUI_NAME } from '$lib/stores';
	import { getContext, onMount } from 'svelte';

	const i18n = getContext<any>('i18n');
	let ollamaVersion = '';

	onMount(async () => {
		ollamaVersion = await getOllamaVersion(localStorage.token).catch(() => '');
	});
</script>

<div id="tab-about" class="flex h-full flex-col space-y-4 text-sm">
	<div>
		<div class="mb-2 text-base font-medium">{$WEBUI_NAME}</div>
		<div class="flex items-center gap-1 text-xs text-gray-700 dark:text-gray-200">
			<span>{$i18n.t('Version')}</span>
			<Tooltip content={WEBUI_BUILD_HASH}>v{WEBUI_VERSION}</Tooltip>
		</div>
	</div>

	<hr class="border-gray-100/30 dark:border-gray-850/30" />

	<div>
		<div class="mb-1 text-sm font-medium">Интеграции</div>
		<div class="text-xs text-gray-500 dark:text-gray-400">
			RAGFlow 0.24 · Консультант по ЛНАД
		</div>
	</div>

	{#if ollamaVersion}
		<hr class="border-gray-100/30 dark:border-gray-850/30" />
		<div>
			<div class="mb-1 text-sm font-medium">{$i18n.t('Ollama Version')}</div>
			<div class="text-xs text-gray-700 dark:text-gray-200">{ollamaVersion}</div>
		</div>
	{/if}

	<div class="mt-auto text-xs text-gray-400 dark:text-gray-500">
		ЛИА 0.2. Условия использования и сведения о лицензировании находятся в файлах проекта.
	</div>
</div>
