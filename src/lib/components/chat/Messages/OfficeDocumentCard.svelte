<script lang="ts">
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { formatFileSize } from '$lib/utils';

	export let file: {
		url: string;
		name: string;
		size?: number;
		content_type?: string;
	};
	export let showPreviewHint = false;

	$: extension = (file?.name?.split('.').pop() ?? '').toLowerCase();
	$: kind =
		extension === 'docx'
			? { label: 'Документ Word', accent: 'blue', monogram: 'W' }
			: extension === 'xlsx'
				? { label: 'Таблица Excel', accent: 'green', monogram: 'X' }
				: { label: 'Презентация PowerPoint', accent: 'orange', monogram: 'P' };

	const download = () => {
		const link = document.createElement('a');
		link.href = `${WEBUI_API_BASE_URL}/files/${file.url}/content?attachment=true`;
		link.download = file.name;
		link.rel = 'noopener';
		document.body.appendChild(link);
		link.click();
		link.remove();
	};
</script>

<div
	class="office-result-card office-{kind.accent} relative overflow-hidden rounded-2xl border bg-white dark:bg-gray-900 px-4 py-3 min-w-[18rem] max-w-[32rem] shadow-sm"
>
	<div class="absolute -right-7 -top-8 size-24 rounded-full opacity-10 accent-bg"></div>
	<div class="relative flex items-center gap-3">
		<div
			class="size-11 shrink-0 rounded-xl accent-bg text-white flex items-center justify-center font-semibold text-lg shadow-sm"
			aria-hidden="true"
		>
			{kind.monogram}
		</div>

		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-1.5 text-[11px] font-medium accent-text">
				<span class="size-1.5 rounded-full accent-bg"></span>
				Готово · {kind.label}
			</div>
			<div class="mt-0.5 truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
				{file.name}
			</div>
			<div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
				{file.size ? formatFileSize(file.size) : extension.toUpperCase()}
				{#if showPreviewHint}<span class="mx-1">·</span>Предпросмотр доступен ниже{/if}
			</div>
		</div>

		<button
			type="button"
			class="shrink-0 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors flex items-center gap-1.5"
			on:click={download}
			aria-label={`Скачать ${file.name}`}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" class="size-4" aria-hidden="true">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="1.8"
					d="M12 3v12m0 0 4-4m-4 4-4-4M5 20h14"
				/>
			</svg>
			Скачать
		</button>
	</div>
</div>

<style>
	.office-result-card {
		border-color: color-mix(in srgb, var(--office-accent) 20%, transparent);
	}
	.office-blue {
		--office-accent: #2563eb;
	}
	.office-green {
		--office-accent: #15803d;
	}
	.office-orange {
		--office-accent: #ea580c;
	}
	.accent-bg {
		background-color: var(--office-accent);
	}
	.accent-text {
		color: var(--office-accent);
	}
</style>
