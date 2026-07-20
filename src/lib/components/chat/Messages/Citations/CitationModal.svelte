<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { settings, config } from '$lib/stores';
	import { injectCsp } from '$lib/utils/csp';

	import XMark from '$lib/components/icons/XMark.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';

	const i18n = getContext('i18n');

	const CONTENT_PREVIEW_LIMIT = 10000;
	let expandedDocs: Set<number> = new Set();

	export let show = false;
	export let citation;
	export let showPercentage = false;
	export let showRelevance = true;

	let mergedDocuments = [];

	function calculatePercentage(distance: number) {
		if (typeof distance !== 'number') return null;
		if (distance < 0) return 0;
		if (distance > 1) return 100;
		return Math.round(distance * 10000) / 100;
	}

	function getRelevanceColor(percentage: number) {
		if (percentage >= 80)
			return 'bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200';
		if (percentage >= 60)
			return 'bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200';
		if (percentage >= 40)
			return 'bg-orange-200 dark:bg-orange-800 text-orange-800 dark:text-orange-200';
		return 'bg-red-200 dark:bg-red-800 text-red-800 dark:text-red-200';
	}

	$: if (citation) {
		expandedDocs = new Set();
		mergedDocuments = citation.document?.map((c, i) => {
			return {
				source: citation.source,
				document: c,
				metadata: citation.metadata?.[i],
				distance: citation.distances?.[i]
			};
		});
		if (mergedDocuments.every((doc) => doc.distance !== undefined)) {
			mergedDocuments = mergedDocuments.sort(
				(a, b) => (b.distance ?? Infinity) - (a.distance ?? Infinity)
			);
		}
	}

	const decodeString = (str: string) => {
		try {
			return decodeURIComponent(str);
		} catch {
			return str;
		}
	};

	const isLink = (value: unknown): value is string =>
		typeof value === 'string' &&
		(value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/'));

	const getDocumentUrl = (doc: any): string | null => {
		const { metadata, source } = doc ?? {};
		if (metadata?.file_id) {
			return `${WEBUI_API_BASE_URL}/files/${metadata.file_id}/content${metadata.page !== undefined ? `#page=${metadata.page + 1}` : ''}`;
		}
		return isLink(source?.url) ? source.url : null;
	};

	const requestDocumentEdit = (doc: any) => {
		const metadata = doc?.metadata ?? {};
		window.dispatchEvent(
			new CustomEvent('lia:edit-ragflow-document', {
				detail: {
					name: metadata.name ?? doc?.source?.name ?? citation?.source?.name,
					datasetName: metadata.dataset_name,
					spaceName: metadata.space_name,
					datasetId: metadata.ragflow_dataset_id,
					documentId: metadata.ragflow_document_id
				}
			})
		);
		show = false;
	};

	const getTextFragmentUrl = (doc: any): string | null => {
		const { document: content } = doc ?? {};
		const baseUrl = getDocumentUrl(doc);

		if (!baseUrl || !content) return baseUrl;

		// Extract first and last words for text fragment, filtering out URLs and emojis
		const words = content
			.trim()
			.replace(/\s+/g, ' ')
			.split(' ')
			.filter((w: string) => w.length > 0 && !/https?:\/\/|[\u{1F300}-\u{1F9FF}]/u.test(w));

		if (words.length === 0) return baseUrl;

		const clean = (w: string) => w.replace(/[^\w]/g, '');
		const first = clean(words[0]);
		const last = clean(words.at(-1));
		const fragment = words.length === 1 ? first : `${first},${last}`;

		return fragment ? `${baseUrl}#:~:text=${fragment}` : baseUrl;
	};
</script>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-4.5 pt-3 pb-2">
			<div class=" text-lg font-medium self-center flex items-center">
				{#if citation?.source?.name}
					{@const document = mergedDocuments?.[0]}
					{#if getDocumentUrl(document)}
						<Tooltip
							className="w-fit"
							content={isLink(document.source?.url) ? $i18n.t('Open link') : $i18n.t('Open file')}
							placement="top-start"
							tippyOptions={{ duration: [500, 0] }}
						>
							<a
								class="hover:text-gray-500 dark:hover:text-gray-100 underline grow line-clamp-1"
								href={getDocumentUrl(document) ?? '#'}
								target="_blank"
							>
								{decodeString(citation?.source?.name)}
							</a>
						</Tooltip>
					{:else}
						{decodeString(citation?.source?.name)}
					{/if}
				{:else}
					{$i18n.t('Citation')}
				{/if}
			</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close citation modal')}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-5 pb-5 md:space-x-4">
			<div
				class="flex flex-col w-full dark:text-gray-200 overflow-y-scroll max-h-[22rem] scrollbar-thin gap-1"
			>
				{#each mergedDocuments as document, documentIdx}
					<div class="flex flex-col w-full gap-2">
						{#if document.metadata?.ragflow}
							<div
								class="flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400"
							>
								{#if document.metadata?.space_name}
									<span class="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-1">
										Пространство: {document.metadata.space_name}
									</span>
								{/if}
								{#if document.metadata?.dataset_name}
									<span class="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-1">
										База: {document.metadata.dataset_name}
									</span>
								{/if}
								{#if getDocumentUrl(document)}
									<a
										class="rounded-full bg-black text-white dark:bg-white dark:text-black px-3 py-1 font-medium hover:opacity-80"
										href={getDocumentUrl(document) ?? '#'}
										target="_blank"
									>
										Открыть оригинал
									</a>
								{/if}
								<button
									type="button"
									class="rounded-full border border-gray-200 dark:border-gray-700 px-3 py-1 font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800"
									on:click={() => requestDocumentEdit(document)}
								>
									Изменить в чате
								</button>
							</div>
						{/if}
						{#if document.metadata?.parameters}
							<div>
								<div class="text-sm font-medium dark:text-gray-300 mb-1">
									{$i18n.t('Parameters')}
								</div>

								<Textarea readonly value={JSON.stringify(document.metadata.parameters, null, 2)}
								></Textarea>
							</div>
						{/if}

						<div>
							<div
								class=" text-sm font-medium dark:text-gray-300 flex items-center gap-2 w-fit mb-1"
							>
								{#if getDocumentUrl(document)}
									{@const snippetUrl = getTextFragmentUrl(document)}
									{#if snippetUrl}
										<a
											href={snippetUrl}
											target="_blank"
											class="underline hover:text-gray-500 dark:hover:text-gray-100"
											>{$i18n.t('Content')}</a
										>
									{:else}
										{$i18n.t('Content')}
									{/if}
								{:else}
									{$i18n.t('Content')}
								{/if}

								{#if showRelevance && document.distance !== undefined}
									<Tooltip
										className="w-fit"
										content={$i18n.t('Relevance')}
										placement="top-start"
										tippyOptions={{ duration: [500, 0] }}
									>
										<div class="text-sm my-1 dark:text-gray-400 flex items-center gap-2 w-fit">
											{#if showPercentage}
												{@const percentage = calculatePercentage(document.distance)}

												{#if typeof percentage === 'number'}
													<span
														class={`px-1 rounded-sm font-medium ${getRelevanceColor(percentage)}`}
													>
														{percentage.toFixed(2)}%
													</span>
												{/if}
											{:else if typeof document?.distance === 'number'}
												<span class="text-gray-500 dark:text-gray-500">
													({(document?.distance ?? 0).toFixed(4)})
												</span>
											{/if}
										</div>
									</Tooltip>
								{/if}

								{#if Number.isInteger(document?.metadata?.page)}
									<span class="text-sm text-gray-500 dark:text-gray-400">
										({$i18n.t('page')}
										{document.metadata.page + 1})
									</span>
								{/if}
							</div>

							{#if document.metadata?.html}
								<iframe
									class="w-full border-0 h-auto rounded-none"
									sandbox="allow-scripts allow-forms{($settings?.iframeSandboxAllowSameOrigin ??
									false)
										? ' allow-same-origin'
										: ''}"
									srcdoc={injectCsp(document.document, $config?.ui?.iframe_csp ?? '')}
									title={$i18n.t('Content')}
								></iframe>
							{:else}
								{@const rawContent = document.document.trim().replace(/\n\n+/g, '\n\n')}
								{@const isTruncated =
									($settings?.renderMarkdownInPreviews ?? true) &&
									rawContent.length > CONTENT_PREVIEW_LIMIT &&
									!expandedDocs.has(documentIdx)}
								{#if $settings?.renderMarkdownInPreviews ?? true}
									<div
										class="text-sm prose dark:prose-invert markdown-prose-sm min-w-full max-w-full"
									>
										<Markdown
											content={isTruncated
												? rawContent.slice(0, CONTENT_PREVIEW_LIMIT)
												: rawContent}
											id="citation-{documentIdx}"
										/>
									</div>
									{#if isTruncated}
										<button
											class="mt-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
											on:click={() => {
												expandedDocs.add(documentIdx);
												expandedDocs = expandedDocs;
											}}
										>
											{$i18n.t('Show all ({{COUNT}} characters)', {
												COUNT: rawContent.length.toLocaleString()
											})}
										</button>
									{/if}
								{:else}
									<pre class="text-sm dark:text-gray-400 whitespace-pre-line">{rawContent}</pre>
								{/if}
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	</div>
</Modal>
