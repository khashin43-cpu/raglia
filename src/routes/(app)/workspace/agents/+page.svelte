<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { getModels } from '$lib/apis';
	import {
		createKnowledgeAgent,
		createKnowledgeDataset,
		createKnowledgeSpace,
		deleteKnowledgeAgent,
		deleteKnowledgeDataset,
		deleteKnowledgeDocument,
		deleteKnowledgeSpace,
		getKnowledgeAgents,
		getKnowledgeDocumentChunks,
		getKnowledgeDocuments,
		getKnowledgeSpaceMembers,
		getKnowledgeSpaces,
		getPendingKnowledgeSpaceInvitations,
		getRAGFlowStatus,
		inviteKnowledgeSpaceMembers,
		removeKnowledgeSpaceMember,
		respondToKnowledgeSpaceInvitation,
		safeRAGFlowFilename,
		updateKnowledgeAgent,
		updateKnowledgeSpace,
		uploadKnowledgeDocuments,
		type KnowledgeAgent,
		type KnowledgeAgentInput,
		type KnowledgeDataset,
		type KnowledgeSpace,
		type KnowledgeSpaceInvitation,
		type KnowledgeSpaceMember,
		type RAGFlowDocument,
		type RAGFlowStatus
	} from '$lib/apis/ragflow';
	import { searchUsers } from '$lib/apis/users';
	import { config, models, settings, user, WEBUI_NAME } from '$lib/stores';
	import Modal from '$lib/components/common/Modal.svelte';
	import Database from '$lib/components/icons/Database.svelte';
	import Document from '$lib/components/icons/Document.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import UserGroup from '$lib/components/icons/UserGroup.svelte';
	import UserPlusSolid from '$lib/components/icons/UserPlusSolid.svelte';

	const AGENT_PREFIX = 'agent:ragflow:';

	let activeTab: 'agents' | 'spaces' = 'agents';
	let status: RAGFlowStatus = { configured: false, version: '0.24' };
	let agents: KnowledgeAgent[] = [];
	let spaces: KnowledgeSpace[] = [];
	let spaceMembers: KnowledgeSpaceMember[] = [];
	let pendingInvitations: KnowledgeSpaceInvitation[] = [];
	let memberSearch = '';
	let memberResults: any[] = [];
	let searchingMembers = false;
	let invitingUserId = '';
	let removingMemberId = '';
	let respondingToInvitation = false;
	let showInvitation = false;
	let memberSearchInput: HTMLInputElement | null = null;
	let loading = true;
	let saving = false;

	let selectedSpaceId = '';
	let selectedDatasetId = '';
	let documents: RAGFlowDocument[] = [];
	let selectedDocumentId = '';
	let chunks: any[] = [];
	let loadingDocuments = false;
	let uploading = false;

	let newDatasetName = '';
	let creatingDataset = false;

	let showSpaceEditor = false;
	let editingSpaceId: string | null = null;
	let spaceName = '';
	let spaceDescription = '';

	let showAgentEditor = false;
	let agentEditorTab: 'general' | 'fine-tuning' = 'general';
	let editingAgentId: string | null = null;
	let agentName = '';
	let agentDescription = '';
	let agentPrompt =
		'Отвечай по подключённым базам знаний. Если сведений недостаточно, прямо скажи об этом.';
	let agentModel = '';
	let agentSpaceIds: string[] = [];
	let agentActive = true;
	let agentTemperature = 0.2;
	let agentTopP = 1;
	let agentMaxTokens = 2048;
	let agentTopK = 30;
	let agentSimilarityThreshold = 0.2;
	let agentVectorWeight = 1;
	let agentFrequencyPenalty = 0;
	let agentPresencePenalty = 0;
	let agentSeed: number | undefined = undefined;
	let agentStop = '';

	$: selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
	$: editingSpace = spaces.find((space) => space.id === editingSpaceId) ?? null;
	$: activeInvitation = pendingInvitations[0] ?? null;
	$: if (activeInvitation) showInvitation = true;
	$: selectedDataset =
		selectedSpace?.datasets?.find((dataset) => dataset.id === selectedDatasetId) ?? null;
	$: availableModels = ($models ?? []).filter((model) => {
		const item = model as any;
		return item?.owned_by !== 'agent' && item?.owned_by !== 'arena' && !item?.pipe;
	});

	const errorMessage = (error: unknown) =>
		error instanceof Error
			? error.message
			: typeof error === 'string'
				? error
				: 'Неизвестная ошибка';

	const refreshNativeModels = async () => {
		models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections ? ($settings?.directConnections ?? null) : null
			)
		);
	};

	const loadAll = async () => {
		loading = true;
		try {
			[status, agents, spaces, pendingInvitations] = await Promise.all([
				getRAGFlowStatus(localStorage.token),
				getKnowledgeAgents(localStorage.token),
				getKnowledgeSpaces(localStorage.token),
				getPendingKnowledgeSpaceInvitations(localStorage.token)
			]);
			if (!selectedSpaceId && spaces.length) selectedSpaceId = spaces[0].id;
			if (selectedSpaceId && !spaces.some((space) => space.id === selectedSpaceId)) {
				selectedSpaceId = spaces[0]?.id ?? '';
			}
			if (selectedSpaceId) await loadSpaceMembers(selectedSpaceId);
			await refreshNativeModels();
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			loading = false;
		}
	};

	onMount(loadAll);

	const loadSpaceMembers = async (spaceId: string) => {
		try {
			spaceMembers = await getKnowledgeSpaceMembers(localStorage.token, spaceId);
		} catch (error) {
			spaceMembers = [];
			toast.error(errorMessage(error));
		}
	};

	const selectSpace = async (space: KnowledgeSpace) => {
		selectedSpaceId = space.id;
		selectedDatasetId = '';
		documents = [];
		await loadSpaceMembers(space.id);
	};

	const openCreateSpace = () => {
		editingSpaceId = null;
		spaceName = '';
		spaceDescription = '';
		showSpaceEditor = true;
	};

	const openEditSpace = async (space: KnowledgeSpace, focusMembers = false) => {
		if (!space.can_manage) return;
		editingSpaceId = space.id;
		spaceName = space.name;
		spaceDescription = space.description ?? '';
		memberSearch = '';
		memberResults = [];
		showSpaceEditor = true;
		await loadSpaceMembers(space.id);
		if (focusMembers) {
			await tick();
			memberSearchInput?.focus();
		}
	};

	const openInviteMembers = (space: KnowledgeSpace) => openEditSpace(space, true);

	const searchMembers = async () => {
		if (!memberSearch.trim()) {
			memberResults = [];
			return;
		}
		searchingMembers = true;
		try {
			const result = await searchUsers(localStorage.token, memberSearch.trim(), 'name', 'asc', 1);
			const existingIds = new Set(spaceMembers.map((member) => member.user_id));
			memberResults = (result?.users ?? []).filter(
				(candidate: any) => candidate.id !== $user?.id && !existingIds.has(candidate.id)
			);
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			searchingMembers = false;
		}
	};

	const inviteMember = async (candidate: any) => {
		if (!editingSpaceId || invitingUserId) return;
		invitingUserId = candidate.id;
		try {
			const result = await inviteKnowledgeSpaceMembers(localStorage.token, editingSpaceId, [
				candidate.id
			]);
			toast.success(
				result.invited_user_ids.length
					? `Приглашение для «${candidate.name || candidate.email}» отправлено`
					: 'Пользователь уже состоит в пространстве'
			);
			memberResults = memberResults.filter((item) => item.id !== candidate.id);
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			invitingUserId = '';
		}
	};

	const removeMember = async (member: KnowledgeSpaceMember) => {
		if (!editingSpaceId || member.role === 'owner' || removingMemberId) return;
		if (!confirm(`Удалить «${member.name || member.email}» из пространства?`)) return;
		removingMemberId = member.user_id;
		try {
			await removeKnowledgeSpaceMember(localStorage.token, editingSpaceId, member.user_id);
			await loadSpaceMembers(editingSpaceId);
			await loadAll();
			toast.success('Доступ пользователя отозван');
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			removingMemberId = '';
		}
	};

	const respondToInvitation = async (accept: boolean) => {
		if (!activeInvitation || respondingToInvitation) return;
		const invitation = activeInvitation;
		respondingToInvitation = true;
		try {
			await respondToKnowledgeSpaceInvitation(localStorage.token, invitation.id, accept);
			showInvitation = false;
			pendingInvitations = pendingInvitations.filter((item) => item.id !== invitation.id);
			if (accept) {
				await loadAll();
				toast.success(`Вы присоединились к пространству «${invitation.space_name}»`);
			} else {
				toast.success('Приглашение отклонено');
			}
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			respondingToInvitation = false;
		}
	};

	const saveSpace = async () => {
		if (!spaceName.trim()) return toast.error('Укажите название пространства');
		saving = true;
		try {
			if (editingSpaceId) {
				await updateKnowledgeSpace(localStorage.token, editingSpaceId, {
					name: spaceName.trim(),
					description: spaceDescription.trim()
				});
				toast.success('Пространство обновлено');
			} else {
				const created = await createKnowledgeSpace(localStorage.token, {
					name: spaceName.trim(),
					description: spaceDescription.trim()
				});
				selectedSpaceId = created.id;
				toast.success('Пространство создано');
			}
			showSpaceEditor = false;
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			saving = false;
		}
	};

	const removeSpace = async (space: KnowledgeSpace) => {
		if (!confirm(`Удалить пространство «${space.name}» и его базы знаний из RAGFlow?`)) return;
		try {
			await deleteKnowledgeSpace(localStorage.token, space.id);
			selectedSpaceId = '';
			selectedDatasetId = '';
			documents = [];
			toast.success('Пространство удалено');
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		}
	};

	const addDataset = async () => {
		if (!selectedSpace || !newDatasetName.trim()) return;
		creatingDataset = true;
		try {
			const dataset = await createKnowledgeDataset(localStorage.token, selectedSpace.id, {
				name: newDatasetName.trim(),
				chunk_method: 'naive'
			});
			newDatasetName = '';
			selectedDatasetId = dataset.id;
			toast.success('База знаний создана в RAGFlow');
			await loadAll();
			await openDataset(dataset);
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			creatingDataset = false;
		}
	};

	const removeDataset = async (dataset: KnowledgeDataset) => {
		if (!confirm(`Удалить базу знаний «${dataset.name}» и все её документы?`)) return;
		try {
			await deleteKnowledgeDataset(localStorage.token, dataset.id);
			selectedDatasetId = '';
			documents = [];
			toast.success('База знаний удалена');
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		}
	};

	const openDataset = async (dataset: KnowledgeDataset) => {
		selectedDatasetId = dataset.id;
		selectedDocumentId = '';
		chunks = [];
		loadingDocuments = true;
		try {
			documents = await getKnowledgeDocuments(localStorage.token, dataset.id);
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			loadingDocuments = false;
		}
	};

	const uploadFiles = async (event: Event) => {
		const input = event.currentTarget as HTMLInputElement;
		const files = Array.from(input.files ?? []);
		if (!selectedDataset || !files.length) return;
		uploading = true;
		try {
			const renamedCount = files.filter(
				(file) => safeRAGFlowFilename(file.name) !== file.name
			).length;
			if (renamedCount > 0) {
				toast.info(
					renamedCount === 1
						? 'Имя файла подготовлено для загрузки в RAGFlow'
						: `Имена файлов подготовлены для загрузки в RAGFlow: ${renamedCount}`
				);
			}
			await uploadKnowledgeDocuments(localStorage.token, selectedDataset.id, files);
			toast.success('Документы загружены, RAGFlow начал обработку');
			await openDataset(selectedDataset);
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			uploading = false;
			input.value = '';
		}
	};

	const removeDocument = async (document: RAGFlowDocument) => {
		if (!selectedDataset || !confirm(`Удалить документ «${document.name || document.doc_name}»?`))
			return;
		try {
			await deleteKnowledgeDocument(localStorage.token, selectedDataset.id, document.id);
			await openDataset(selectedDataset);
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		}
	};

	const openDocument = async (document: RAGFlowDocument) => {
		if (!selectedDataset) return;
		selectedDocumentId = document.id;
		try {
			chunks = await getKnowledgeDocumentChunks(
				localStorage.token,
				selectedDataset.id,
				document.id
			);
		} catch (error) {
			toast.error(errorMessage(error));
		}
	};

	const resetAgentForm = () => {
		editingAgentId = null;
		agentName = '';
		agentDescription = '';
		agentPrompt =
			'Отвечай по подключённым базам знаний. Если сведений недостаточно, прямо скажи об этом.';
		agentModel = '';
		agentSpaceIds = selectedSpaceId ? [selectedSpaceId] : [];
		agentActive = true;
		agentTemperature = 0.2;
		agentTopP = 1;
		agentMaxTokens = 2048;
		agentTopK = 30;
		agentSimilarityThreshold = 0.2;
		agentVectorWeight = 1;
		agentFrequencyPenalty = 0;
		agentPresencePenalty = 0;
		agentSeed = undefined;
		agentStop = '';
	};

	const openCreateAgent = () => {
		resetAgentForm();
		agentEditorTab = 'general';
		showAgentEditor = true;
	};

	const openEditAgent = (agent: KnowledgeAgent) => {
		editingAgentId = agent.id;
		agentName = agent.name;
		agentDescription = agent.description ?? '';
		agentPrompt = agent.prompt ?? '';
		agentModel = agent.model ?? '';
		agentSpaceIds = [...(agent.space_ids ?? [])];
		agentActive = agent.active ?? true;
		agentTemperature = agent.params?.temperature ?? 0.2;
		agentTopP = agent.params?.top_p ?? 1;
		agentMaxTokens = agent.params?.max_tokens ?? 2048;
		agentTopK = agent.params?.top_k ?? 30;
		agentSimilarityThreshold = agent.params?.similarity_threshold ?? 0.2;
		agentVectorWeight = agent.params?.vector_similarity_weight ?? 1;
		agentFrequencyPenalty = agent.params?.frequency_penalty ?? 0;
		agentPresencePenalty = agent.params?.presence_penalty ?? 0;
		agentSeed = agent.params?.seed;
		agentStop = (agent.params?.stop ?? []).join('\n');
		agentEditorTab = 'general';
		showAgentEditor = true;
	};

	const toggleAgentSpace = (spaceId: string) => {
		agentSpaceIds = agentSpaceIds.includes(spaceId)
			? agentSpaceIds.filter((id) => id !== spaceId)
			: [...agentSpaceIds, spaceId];
	};

	const saveAgent = async () => {
		if (!agentName.trim()) return toast.error('Укажите имя ассистента');
		if (!agentSpaceIds.length) return toast.error('Подключите хотя бы одно пространство');
		const stopSequences = agentStop
			.split('\n')
			.map((item) => item.trim())
			.filter(Boolean)
			.slice(0, 4);
		const payload: KnowledgeAgentInput = {
			name: agentName.trim(),
			description: agentDescription.trim(),
			prompt: agentPrompt.trim(),
			model: agentModel.trim(),
			space_ids: agentSpaceIds,
			active: agentActive,
			params: {
				temperature: Number(agentTemperature),
				top_p: Number(agentTopP),
				max_tokens: Number(agentMaxTokens),
				top_k: Number(agentTopK),
				similarity_threshold: Number(agentSimilarityThreshold),
				vector_similarity_weight: Number(agentVectorWeight),
				frequency_penalty: Number(agentFrequencyPenalty),
				presence_penalty: Number(agentPresencePenalty),
				...(typeof agentSeed === 'number' && Number.isInteger(agentSeed)
					? { seed: agentSeed }
					: {}),
				...(stopSequences.length ? { stop: stopSequences } : {})
			}
		};
		saving = true;
		try {
			if (editingAgentId) {
				await updateKnowledgeAgent(localStorage.token, editingAgentId, payload);
				toast.success('Ассистент обновлён');
			} else {
				await createKnowledgeAgent(localStorage.token, payload);
				toast.success('Ассистент создан');
			}
			showAgentEditor = false;
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			saving = false;
		}
	};

	const removeAgent = async (agent: KnowledgeAgent) => {
		if (!confirm(`Удалить ассистента «${agent.name}»? Базы знаний останутся.`)) return;
		try {
			await deleteKnowledgeAgent(localStorage.token, agent.id);
			toast.success('Ассистент удалён');
			await loadAll();
		} catch (error) {
			toast.error(errorMessage(error));
		}
	};
</script>

<svelte:head><title>Ассистенты по Вашим базам знаний • {$WEBUI_NAME}</title></svelte:head>

<div class="mx-auto w-full max-w-7xl px-4 py-8 md:px-8">
	<div class="mb-7 flex flex-wrap items-start justify-between gap-4">
		<div class="flex items-center gap-3">
			<div class="flex size-10 items-center justify-center rounded-xl bg-gray-100 dark:bg-gray-850">
				<UserGroup className="size-5" strokeWidth="1.75" />
			</div>
			<div>
				<h1 class="text-2xl font-semibold">Ассистенты по Вашим базам знаний</h1>
				<p class="text-sm text-gray-500">LLM → пространства → базы знаний → документы RAGFlow</p>
			</div>
		</div>
		<div class="flex items-center gap-2 text-xs text-gray-500" title={status.error ?? ''}>
			<span class="size-2 rounded-full {status.connected ? 'bg-emerald-500' : 'bg-amber-500'}"
			></span>
			{status.connected
				? `RAGFlow ${status.version} · ${status.url}`
				: status.configured
					? `RAGFlow ${status.version} недоступен`
					: 'RAGFlow не подключён'}
		</div>
	</div>

	<div class="mb-6 flex items-center justify-between border-b border-gray-200 dark:border-gray-800">
		<div class="flex gap-6">
			<button
				class="border-b-2 px-1 pb-3 text-sm font-medium {activeTab === 'agents'
					? 'border-gray-900 dark:border-white'
					: 'border-transparent text-gray-500'}"
				on:click={() => (activeTab = 'agents')}
				>Ассистенты по Вашим базам знаний <span class="ml-1 text-xs text-gray-400"
					>{agents.length}</span
				></button
			>
			<button
				class="border-b-2 px-1 pb-3 text-sm font-medium {activeTab === 'spaces'
					? 'border-gray-900 dark:border-white'
					: 'border-transparent text-gray-500'}"
				on:click={() => (activeTab = 'spaces')}
				>Пространства <span class="ml-1 text-xs text-gray-400">{spaces.length}</span></button
			>
		</div>
		<button
			class="mb-2 flex h-9 items-center gap-2 rounded-full bg-gray-900 px-4 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
			disabled={!status.configured && activeTab === 'agents'}
			on:click={activeTab === 'agents' ? openCreateAgent : openCreateSpace}
		>
			<Plus className="size-4" />{activeTab === 'agents' ? 'Новый ассистент' : 'Новое пространство'}
		</button>
	</div>

	{#if loading}
		<div class="grid gap-3 md:grid-cols-2">
			{#each Array(4) as _}<div
					class="h-28 animate-pulse rounded-2xl bg-gray-100 dark:bg-gray-850"
				></div>{/each}
		</div>
	{:else if !status.configured}
		<div
			class="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
		>
			<div class="font-medium">RAGFlow не подключён</div>
			<div class="mt-1 opacity-80">
				Заполните RAGFLOW_URL и RAGFLOW_API_KEY в `.env`, затем перезапустите backend.
			</div>
		</div>
	{:else if activeTab === 'agents'}
		{#if agents.length === 0}
			<div
				class="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-gray-200 text-center dark:border-gray-800"
			>
				<UserGroup className="mb-3 size-9 text-gray-400" />
				<div class="font-medium">Ассистентов пока нет</div>
				<div class="mt-1 text-sm text-gray-500">
					Сначала создайте пространство и базу знаний, затем подключите их к LLM.
				</div>
			</div>
		{:else}
			<div class="grid gap-3 md:grid-cols-2">
				{#each agents as agent (agent.id)}
					<div
						class="flex items-center gap-4 rounded-2xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
					>
						<button
							class="flex min-w-0 flex-1 items-center gap-4 text-left"
							on:click={() => goto(`/?model=${encodeURIComponent(`${AGENT_PREFIX}${agent.id}`)}`)}
						>
							<div
								class="flex size-11 shrink-0 items-center justify-center rounded-full bg-gray-100 font-medium dark:bg-gray-850"
							>
								{agent.name.slice(0, 1).toUpperCase()}
							</div>
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2">
									<div class="truncate font-medium">{agent.name}</div>
									{#if agent.shared}<span
											class="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
											>Общий</span
										>{/if}
									<span
										class="rounded-full px-2 py-0.5 text-[11px] {agent.active
											? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
											: 'bg-gray-100 text-gray-500 dark:bg-gray-800'}"
										>{agent.active ? 'Активен' : 'Выключен'}</span
									>
								</div>
								<div class="mt-1 line-clamp-1 text-sm text-gray-500">
									{agent.description || 'Без описания'}
								</div>
								<div class="mt-1 text-xs text-gray-400">
									{agent.space_ids.length} пространств · {agent.dataset_ids?.length ?? 0} баз · {agent.model ||
										'Ария (по умолчанию)'}
								</div>
							</div>
						</button>
						{#if agent.can_edit !== false}<button
								class="rounded-lg p-2 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
								title="Редактировать"
								on:click={() => openEditAgent(agent)}><Pencil className="size-4" /></button
							>{/if}
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<div class="grid min-h-[32rem] gap-4 lg:grid-cols-[18rem_1fr]">
			<div class="rounded-2xl border border-gray-200 p-2 dark:border-gray-800">
				{#if spaces.length === 0}<div class="p-6 text-center text-sm text-gray-500">
						Нет пространств
					</div>{/if}
				{#each spaces as space (space.id)}
					<div
						class="mb-1 flex w-full items-center gap-1 rounded-xl {selectedSpaceId === space.id
							? 'bg-gray-100 dark:bg-gray-850'
							: 'hover:bg-gray-50 dark:hover:bg-gray-900'}"
					>
						<button
							class="flex min-w-0 flex-1 items-center gap-3 px-3 py-2.5 text-left"
							on:click={() => selectSpace(space)}
						>
							<Folder className="size-5 shrink-0 text-gray-500" />
							<div class="min-w-0 flex-1">
								<div class="truncate text-sm font-medium">{space.name}</div>
								<div class="flex items-center gap-1.5 text-xs text-gray-500">
									<span>{space.datasets?.length ?? 0} баз знаний</span>
									{#if space.is_shared}<span>· {space.member_count ?? 1} участников</span>{/if}
								</div>
							</div>
						</button>
						{#if space.can_manage}<button
								class="rounded-lg p-1.5 text-gray-400 hover:bg-white hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
								title="Пригласить участника"
								on:click={() => openInviteMembers(space)}
								><UserPlusSolid className="size-3.5" /></button
							><button
								class="mr-2 rounded-lg p-1.5 text-gray-400 hover:bg-white hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
								title="Настроить"
								on:click={() => openEditSpace(space)}><Pencil className="size-3.5" /></button
							>{:else}<span
								class="mr-2 rounded-full bg-blue-50 px-2 py-1 text-[10px] font-medium text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
								>Общее</span
							>{/if}
					</div>
				{/each}
			</div>

			<div class="rounded-2xl border border-gray-200 p-5 dark:border-gray-800">
				{#if !selectedSpace}
					<div class="flex h-full items-center justify-center text-sm text-gray-500">
						Выберите пространство
					</div>
				{:else}
					<div class="mb-5">
						<div class="flex flex-wrap items-center gap-2">
							<h2 class="text-lg font-semibold">{selectedSpace.name}</h2>
							{#if selectedSpace.can_manage}<button
									class="flex items-center gap-1.5 rounded-full border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
									type="button"
									on:click={() => openInviteMembers(selectedSpace)}
									><UserPlusSolid className="size-3.5" />Пригласить</button
								>{/if}
							{#if selectedSpace.role === 'member'}<span
									class="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
									>Доступ предоставлен владельцем</span
								>{/if}
						</div>
						<p class="mt-1 text-sm text-gray-500">
							{selectedSpace.description ||
								'В пространстве объединяются базы знаний, доступные ассистентам.'}
						</p>
					</div>
					<div class="mb-4 flex gap-2">
						<input
							class="min-w-0 flex-1 rounded-xl border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
							placeholder="Название новой базы знаний"
							bind:value={newDatasetName}
							on:keydown={(event) => event.key === 'Enter' && addDataset()}
						/><button
							class="rounded-xl bg-gray-900 px-4 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
							disabled={!newDatasetName.trim() || creatingDataset}
							on:click={addDataset}>{creatingDataset ? 'Создание…' : 'Создать базу'}</button
						>
					</div>

					<div class="grid gap-3 xl:grid-cols-2">
						{#each selectedSpace.datasets ?? [] as dataset (dataset.id)}
							<div
								class="rounded-xl border p-3 {selectedDatasetId === dataset.id
									? 'border-gray-400 dark:border-gray-500'
									: 'border-gray-200 dark:border-gray-800'}"
							>
								<div class="flex items-start gap-3">
									<Database className="mt-0.5 size-5 text-gray-500" /><button
										class="min-w-0 flex-1 text-left"
										on:click={() => openDataset(dataset)}
										><div class="truncate text-sm font-medium">{dataset.name}</div>
										<div class="mt-1 text-xs text-gray-500">
											{dataset.doc_count ?? 0} документов · {dataset.chunk_method ?? 'naive'}
										</div></button
									><button class="text-xs text-red-500" on:click={() => removeDataset(dataset)}
										>Удалить</button
									>
								</div>
							</div>
						{/each}
					</div>

					{#if selectedDataset}
						<div class="mt-6 border-t border-gray-200 pt-5 dark:border-gray-800">
							<div class="mb-3 flex items-center justify-between">
								<div>
									<div class="font-medium">{selectedDataset.name}</div>
									<div class="text-xs text-gray-500">
										Документы хранятся и индексируются в RAGFlow
									</div>
								</div>
								<label
									class="cursor-pointer rounded-full bg-gray-900 px-4 py-2 text-sm font-medium text-white dark:bg-white dark:text-gray-900"
									>{uploading ? 'Загрузка…' : 'Загрузить документы'}<input
										class="hidden"
										type="file"
										multiple
										disabled={uploading}
										on:change={uploadFiles}
									/></label
								>
							</div>
							<div class="grid gap-4 xl:grid-cols-[20rem_1fr]">
								<div
									class="max-h-80 overflow-y-auto rounded-xl border border-gray-200 p-1 dark:border-gray-800"
								>
									{#if loadingDocuments}<div class="p-5 text-center text-sm text-gray-500">
											Загрузка…
										</div>{:else if documents.length === 0}<div
											class="p-5 text-center text-sm text-gray-500"
										>
											Документов пока нет
										</div>{/if}
									{#each documents as document (document.id)}<div
											class="flex items-center gap-2 rounded-lg px-2 py-2 {selectedDocumentId ===
											document.id
												? 'bg-gray-100 dark:bg-gray-850'
												: ''}"
										>
											<button
												class="flex min-w-0 flex-1 items-center gap-2 text-left"
												on:click={() => openDocument(document)}
												><Document className="size-4 shrink-0 text-gray-500" /><span class="min-w-0"
													><span class="block truncate text-sm"
														>{document.name || document.doc_name || document.id}</span
													><span class="block text-[11px] text-gray-500"
														>{document.run || 'загружен'} · {document.chunk_count ?? 0} чанков</span
													></span
												></button
											><button
												class="text-xs text-red-500"
												on:click={() => removeDocument(document)}>×</button
											>
										</div>{/each}
								</div>
								<div class="max-h-80 overflow-y-auto rounded-xl bg-gray-50 p-3 dark:bg-gray-950">
									{#if !selectedDocumentId}<div class="p-5 text-center text-sm text-gray-500">
											Выберите документ, чтобы посмотреть чанки
										</div>{:else if chunks.length === 0}<div
											class="p-5 text-center text-sm text-gray-500"
										>
											Чанки пока не готовы
										</div>{:else}{#each chunks as chunk, index}<div
												class="mb-3 rounded-xl bg-white p-3 text-xs leading-5 dark:bg-gray-900"
											>
												<div class="mb-1 font-medium">Фрагмент {index + 1}</div>
												{chunk.content || chunk.text || JSON.stringify(chunk)}
											</div>{/each}{/if}
								</div>
							</div>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	{/if}
</div>

<Modal bind:show={showSpaceEditor} size="md">
	<div class="max-h-[85vh] overflow-y-auto p-6">
		<h2 class="text-xl font-semibold">
			{editingSpaceId ? 'Настройка пространства' : 'Новое пространство'}
		</h2>
		<div class="mt-5 space-y-4">
			<label class="block"
				><span class="mb-1.5 block text-sm font-medium">Название</span><input
					class="w-full rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none dark:border-gray-700"
					bind:value={spaceName}
				/></label
			><label class="block"
				><span class="mb-1.5 block text-sm font-medium">Описание</span><textarea
					rows="3"
					class="w-full resize-none rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none dark:border-gray-700"
					bind:value={spaceDescription}
				></textarea></label
			>
			{#if editingSpaceId && editingSpace?.can_manage}
				<div class="border-t border-gray-200 pt-4 dark:border-gray-800">
					<div class="mb-1 text-sm font-medium">Участники пространства</div>
					<p class="mb-3 text-xs text-gray-500">
						Участникам доступны базы знаний и ассистенты, полностью подключённые к этому
						пространству.
					</p>
					<div class="flex gap-2">
						<input
							bind:this={memberSearchInput}
							class="min-w-0 flex-1 rounded-xl border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
							placeholder="Имя или корпоративная почта"
							bind:value={memberSearch}
							on:keydown={(event) => event.key === 'Enter' && searchMembers()}
						/>
						<button
							class="rounded-xl bg-gray-100 px-3 text-sm disabled:opacity-50 dark:bg-gray-800"
							disabled={searchingMembers || !memberSearch.trim()}
							on:click={searchMembers}>{searchingMembers ? 'Поиск…' : 'Найти'}</button
						>
					</div>
					{#if memberResults.length}
						<div
							class="mt-2 max-h-36 space-y-1 overflow-y-auto rounded-xl bg-gray-50 p-1 dark:bg-gray-950"
						>
							{#each memberResults as candidate (candidate.id)}
								<div class="flex items-center gap-3 rounded-lg bg-white px-3 py-2 dark:bg-gray-900">
									<div class="min-w-0 flex-1">
										<div class="truncate text-sm font-medium">
											{candidate.name || candidate.email}
										</div>
										<div class="truncate text-xs text-gray-500">{candidate.email}</div>
									</div>
									<button
										class="rounded-full bg-gray-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
										disabled={Boolean(invitingUserId)}
										on:click={() => inviteMember(candidate)}
										>{invitingUserId === candidate.id ? 'Отправка…' : 'Пригласить'}</button
									>
								</div>
							{/each}
						</div>
					{/if}
					<div class="mt-3 max-h-40 space-y-1 overflow-y-auto">
						{#each spaceMembers as member (member.user_id)}
							<div
								class="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-gray-50 dark:hover:bg-gray-900"
							>
								<div
									class="flex size-8 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-medium dark:bg-gray-800"
								>
									{(member.name || member.email || '?').slice(0, 1).toUpperCase()}
								</div>
								<div class="min-w-0 flex-1">
									<div class="truncate text-sm">{member.name || member.email}</div>
									<div class="truncate text-xs text-gray-500">{member.email}</div>
								</div>
								{#if member.role === 'owner'}
									<span class="text-xs text-gray-400">Владелец</span>
								{:else}
									<button
										class="rounded-full px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
										disabled={Boolean(removingMemberId)}
										on:click={() => removeMember(member)}
										>{removingMemberId === member.user_id ? 'Удаление…' : 'Удалить'}</button
									>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
		<div class="mt-6 flex justify-between">
			<div>
				{#if editingSpaceId && editingSpace?.can_manage}<button
						class="rounded-full px-3 py-2 text-sm text-red-600 hover:bg-red-50"
						on:click={async () => {
							const space = spaces.find((item) => item.id === editingSpaceId);
							if (space) {
								showSpaceEditor = false;
								await removeSpace(space);
							}
						}}>Удалить</button
					>{/if}
			</div>
			<div class="flex gap-2">
				<button
					class="rounded-full px-4 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
					on:click={() => (showSpaceEditor = false)}>Отмена</button
				><button
					class="rounded-full bg-gray-900 px-5 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
					disabled={saving}
					on:click={saveSpace}>Сохранить</button
				>
			</div>
		</div>
	</div>
</Modal>

<Modal bind:show={showInvitation} size="sm">
	{#if activeInvitation}
		<div class="p-6">
			<div
				class="flex size-11 items-center justify-center rounded-full bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
			>
				<UserGroup className="size-5" />
			</div>
			<h2 class="mt-4 text-xl font-semibold">Приглашение в пространство</h2>
			<p class="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
				<strong>{activeInvitation.inviter_name}</strong> приглашает Вас в пространство
				<strong>«{activeInvitation.space_name}»</strong>. После принятия станут доступны его базы
				знаний и общие ассистенты.
			</p>
			<div class="mt-6 flex justify-end gap-2">
				<button
					class="rounded-full px-4 py-2 text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800"
					disabled={respondingToInvitation}
					on:click={() => respondToInvitation(false)}>Отклонить</button
				>
				<button
					class="rounded-full bg-gray-900 px-5 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
					disabled={respondingToInvitation}
					on:click={() => respondToInvitation(true)}
					>{respondingToInvitation ? 'Обработка…' : 'Присоединиться'}</button
				>
			</div>
		</div>
	{/if}
</Modal>

<Modal bind:show={showAgentEditor} size="lg">
	<div class="flex max-h-[85vh] min-h-[38rem] flex-col">
		<div class="shrink-0 px-6 pt-6">
			<h2 class="text-xl font-semibold">
				{editingAgentId ? 'Редактирование ассистента' : 'Новый ассистент'}
			</h2>
			<p class="mt-1 text-sm text-gray-500">
				Ассистент использует знания из подключённых пространств и системную модель Ария.
			</p>

			<div class="mt-5 flex gap-6 border-b border-gray-200 dark:border-gray-800">
				<button
					type="button"
					class="border-b-2 px-1 pb-3 text-sm font-medium transition-colors {agentEditorTab ===
					'general'
						? 'border-gray-900 text-gray-900 dark:border-white dark:text-white'
						: 'border-transparent text-gray-500 hover:text-gray-800 dark:hover:text-gray-200'}"
					on:click={() => (agentEditorTab = 'general')}
				>
					Основное
				</button>
				<button
					type="button"
					class="border-b-2 px-1 pb-3 text-sm font-medium transition-colors {agentEditorTab ===
					'fine-tuning'
						? 'border-gray-900 text-gray-900 dark:border-white dark:text-white'
						: 'border-transparent text-gray-500 hover:text-gray-800 dark:hover:text-gray-200'}"
					on:click={() => (agentEditorTab = 'fine-tuning')}
				>
					Тонкая настройка
				</button>
			</div>
		</div>

		<div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
			{#if agentEditorTab === 'general'}
				<div class="space-y-5">
					<div>
						<label class="block">
							<span class="mb-1.5 block text-sm font-medium">Имя</span>
							<input
								class="w-full rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none dark:border-gray-700"
								bind:value={agentName}
							/>
						</label>
					</div>

					<label class="block">
						<span class="mb-1.5 block text-sm font-medium">Описание</span>
						<textarea
							rows="2"
							class="w-full resize-none rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none dark:border-gray-700"
							bind:value={agentDescription}
						></textarea>
					</label>

					<label class="block">
						<span class="mb-1.5 block text-sm font-medium">Системный промпт</span>
						<span class="mb-2 block text-xs leading-5 text-gray-500">
							Постоянная инструкция определяет роль, стиль ответа и ограничения ассистента.
						</span>
						<textarea
							rows="5"
							class="w-full resize-none rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none dark:border-gray-700"
							bind:value={agentPrompt}
						></textarea>
					</label>

					<div>
						<div class="mb-2 text-sm font-medium">Пространства</div>
						<div
							class="grid gap-2 rounded-xl border border-gray-200 p-2 dark:border-gray-700 md:grid-cols-2"
						>
							{#if spaces.length === 0}
								<div class="col-span-full p-4 text-center text-sm text-gray-500">
									Сначала создайте пространство
								</div>
							{/if}
							{#each spaces as space (space.id)}
								<button
									type="button"
									class="flex items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-800"
									on:click={() => toggleAgentSpace(space.id)}
								>
									<span
										class="flex size-4 items-center justify-center rounded border text-xs {agentSpaceIds.includes(
											space.id
										)
											? 'border-gray-900 bg-gray-900 text-white dark:border-white dark:bg-white dark:text-gray-900'
											: 'border-gray-300 dark:border-gray-600'}"
									>
										{agentSpaceIds.includes(space.id) ? '✓' : ''}
									</span>
									<span class="min-w-0">
										<span class="block truncate text-sm">{space.name}</span>
										<span class="block text-xs text-gray-500"
											>{space.datasets?.length ?? 0} баз знаний</span
										>
									</span>
								</button>
							{/each}
						</div>
					</div>

					<label class="flex items-center gap-3 text-sm">
						<input type="checkbox" bind:checked={agentActive} />
						Ассистент активен и отображается в селекторе чата
					</label>
				</div>
			{:else}
				<div class="space-y-5">
					<div class="rounded-2xl border border-gray-200 p-4 dark:border-gray-800">
						<div class="mb-4">
							<div class="text-sm font-medium">Генерация ответа</div>
							<p class="mt-1 text-xs leading-5 text-gray-500">
								По умолчанию ответы формирует Ария. При необходимости можно выбрать другую
								подключённую LLM.
							</p>
						</div>
						<div class="grid gap-4 md:grid-cols-2">
							<label class="text-xs md:col-span-2">
								Модель ответа
								<select
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentModel}
								>
									<option value="">По умолчанию — Ария</option>
									{#each availableModels as model (model.id)}
										<option value={model.id}>{model.name || model.id}</option>
									{/each}
								</select>
								<span class="mt-1 block leading-5 text-gray-500">
									Используется LIA_ARIA_MODEL из переменных окружения сервера.
								</span>
							</label>
							<label class="text-xs">
								Максимум токенов ответа (max_tokens)
								<input
									type="number"
									min="1"
									max="131072"
									step="1"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentMaxTokens}
								/>
							</label>
							<label class="text-xs">
								Начальное значение генератора (seed)
								<input
									type="number"
									step="1"
									placeholder="Случайное"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentSeed}
								/>
							</label>
							<label class="text-xs">
								Температура (temperature)
								<input
									type="number"
									min="0"
									max="2"
									step="0.1"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentTemperature}
								/>
							</label>
							<label class="text-xs">
								Порог вероятностной выборки (top_p)
								<input
									type="number"
									min="0"
									max="1"
									step="0.05"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentTopP}
								/>
							</label>
							<label class="text-xs">
								Штраф за повторение (frequency_penalty)
								<input
									type="number"
									min="-2"
									max="2"
									step="0.1"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentFrequencyPenalty}
								/>
							</label>
							<label class="text-xs">
								Штраф за присутствие (presence_penalty)
								<input
									type="number"
									min="-2"
									max="2"
									step="0.1"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentPresencePenalty}
								/>
							</label>
							<label class="text-xs md:col-span-2">
								Стоп-последовательности (stop)
								<textarea
									rows="3"
									placeholder="По одной последовательности на строку, не более четырёх"
									class="mt-1 w-full resize-none rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentStop}
								></textarea>
							</label>
						</div>
					</div>

					<div class="rounded-2xl border border-gray-200 p-4 dark:border-gray-800">
						<div class="mb-4">
							<div class="text-sm font-medium">Поиск по базам знаний</div>
							<p class="mt-1 text-xs leading-5 text-gray-500">
								Параметры определяют объём и точность контекста, получаемого из RAGFlow 0.24.
							</p>
						</div>
						<div class="grid gap-4 md:grid-cols-2">
							<label class="text-xs">
								Количество фрагментов (top_k)
								<input
									type="number"
									min="1"
									max="100"
									step="1"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentTopK}
								/>
							</label>
							<label class="text-xs">
								Порог сходства (similarity_threshold)
								<input
									type="number"
									min="0"
									max="1"
									step="0.05"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentSimilarityThreshold}
								/>
							</label>
							<label class="text-xs md:col-span-2">
								Вес векторного поиска (vector_similarity_weight)
								<input
									type="number"
									min="0"
									max="1"
									step="0.05"
									class="mt-1 w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={agentVectorWeight}
								/>
							</label>
						</div>
					</div>
				</div>
			{/if}
		</div>

		<div
			class="flex shrink-0 items-center justify-between border-t border-gray-200 px-6 py-4 dark:border-gray-800"
		>
			<div>
				{#if editingAgentId}
					<button
						type="button"
						class="rounded-full px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
						on:click={async () => {
							const agent = agents.find((item) => item.id === editingAgentId);
							if (agent) {
								showAgentEditor = false;
								await removeAgent(agent);
							}
						}}
					>
						Удалить
					</button>
				{/if}
			</div>
			<div class="flex gap-2">
				<button
					type="button"
					class="rounded-full px-4 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
					on:click={() => (showAgentEditor = false)}
				>
					Отмена
				</button>
				<button
					type="button"
					class="rounded-full bg-gray-900 px-5 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
					disabled={saving}
					on:click={saveAgent}
				>
					{saving ? 'Сохранение…' : 'Сохранить'}
				</button>
			</div>
		</div>
	</div>
</Modal>
