import { WEBUI_API_BASE_URL } from '$lib/constants';

export const RAGFLOW_FILENAME_MAX_BYTES = 255;
const RAGFLOW_MULTIPART_FILENAME_MAX_BYTES = 200;

const CYRILLIC_TRANSLITERATION: Record<string, string> = {
	а: 'a',
	б: 'b',
	в: 'v',
	г: 'g',
	д: 'd',
	е: 'e',
	ё: 'e',
	ж: 'zh',
	з: 'z',
	и: 'i',
	й: 'i',
	к: 'k',
	л: 'l',
	м: 'm',
	н: 'n',
	о: 'o',
	п: 'p',
	р: 'r',
	с: 's',
	т: 't',
	у: 'u',
	ф: 'f',
	х: 'h',
	ц: 'ts',
	ч: 'ch',
	ш: 'sh',
	щ: 'sch',
	ъ: '',
	ы: 'y',
	ь: '',
	э: 'e',
	ю: 'yu',
	я: 'ya'
};

const utf8Length = (value: string) => new TextEncoder().encode(value).length;

const truncateUtf8 = (value: string, maxBytes: number) => {
	let result = '';
	let size = 0;
	for (const char of value) {
		const charSize = utf8Length(char);
		if (size + charSize > maxBytes) break;
		result += char;
		size += charSize;
	}
	return result;
};

const filenameHash = (value: string) => {
	let hash = 0x811c9dc5;
	for (const byte of new TextEncoder().encode(value)) {
		hash ^= byte;
		hash = Math.imul(hash, 0x01000193);
	}
	return (hash >>> 0).toString(16).padStart(8, '0');
};

export const safeRAGFlowFilename = (filename: string) => {
	const normalized = (filename || 'document')
		.normalize('NFC')
		.replace(/[\u0000-\u001f]/g, '_')
		.trim();
	const original = normalized || 'document';
	if (
		/^[A-Za-z0-9._-]+$/.test(original) &&
		utf8Length(original) <= RAGFLOW_MULTIPART_FILENAME_MAX_BYTES
	) {
		return original;
	}

	const transliterate = (value: string) =>
		Array.from(value, (char) => {
			const replacement = CYRILLIC_TRANSLITERATION[char.toLowerCase()];
			if (replacement === undefined) return char;
			return char === char.toUpperCase() && replacement
				? replacement[0].toUpperCase() + replacement.slice(1)
				: replacement;
		})
			.join('')
			.normalize('NFKD')
			.replace(/[\u0300-\u036f]/g, '')
			.replace(/[^A-Za-z0-9._-]+/g, '-')
			.replace(/-{2,}/g, '-')
			.replace(/^[ ._-]+|[ ._-]+$/g, '');

	const originalDotIndex = original.lastIndexOf('.');
	const originalStem = originalDotIndex > 0 ? original.slice(0, originalDotIndex) : original;
	const originalExtension = originalDotIndex > 0 ? original.slice(originalDotIndex + 1) : '';
	const stem = transliterate(originalStem) || 'document';
	const asciiExtension = transliterate(originalExtension);
	const suffix = asciiExtension ? `.${truncateUtf8(asciiExtension, 15)}` : '';
	const tail = `-${filenameHash(original)}${suffix}`;
	const stemBudget = RAGFLOW_MULTIPART_FILENAME_MAX_BYTES - utf8Length(tail);
	const shortenedStem = truncateUtf8(stem, stemBudget).replace(/[ ._-]+$/g, '') || 'document';
	return `${shortenedStem}${tail}`;
};

export type RAGFlowStatus = {
	configured: boolean;
	connected?: boolean;
	url?: string | null;
	version: string;
	mode?: string;
	error?: string | null;
};

export type KnowledgeDataset = {
	id: string;
	name: string;
	chunk_method?: string;
	doc_count?: number;
	created_at?: number;
	updated_at?: number;
};

export type KnowledgeSpace = {
	id: string;
	owner_id?: string;
	name: string;
	description?: string;
	datasets: KnowledgeDataset[];
	role?: 'owner' | 'member';
	can_manage?: boolean;
	is_shared?: boolean;
	member_count?: number;
	created_at?: number;
	updated_at?: number;
};

export type KnowledgeSpaceMember = {
	user_id: string;
	role: 'owner' | 'member';
	name: string;
	email: string;
	profile_image_url?: string | null;
	joined_at?: number;
};

export type KnowledgeSpaceInvitation = {
	id: string;
	space_id: string;
	space_name: string;
	owner_id: string;
	invited_by: string;
	inviter_name: string;
	status: 'pending' | 'accepted' | 'declined';
	created_at?: number;
};

export type KnowledgeAgentParams = {
	max_tokens?: number;
	temperature?: number;
	top_p?: number;
	frequency_penalty?: number;
	presence_penalty?: number;
	seed?: number;
	stop?: string[];
	top_k?: number;
	similarity_threshold?: number;
	vector_similarity_weight?: number;
};

export type KnowledgeAgent = {
	id: string;
	owner_id?: string;
	name: string;
	description: string;
	prompt: string;
	model: string;
	space_ids: string[];
	params: KnowledgeAgentParams;
	active: boolean;
	can_edit?: boolean;
	shared?: boolean;
	dataset_ids?: string[];
	ragflow_chat_id?: string | null;
	created_at?: number;
	updated_at?: number;
};

export type RAGFlowDocument = {
	id: string;
	name?: string;
	doc_name?: string;
	run?: string;
	progress?: number;
	progress_msg?: string;
	chunk_count?: number;
	[key: string]: any;
};

const request = async <T>(token: string, path: string, init: RequestInit = {}): Promise<T> => {
	const isForm = init.body instanceof FormData;
	const response = await fetch(`${WEBUI_API_BASE_URL}/ragflow${path}`, {
		...init,
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`,
			...(isForm ? {} : { 'Content-Type': 'application/json' }),
			...init.headers
		}
	});

	if (!response.ok) {
		let detail = `Request failed (${response.status})`;
		try {
			const payload = await response.json();
			detail = payload?.detail || payload?.message || detail;
		} catch {
			// Preserve the HTTP fallback for non-JSON errors.
		}
		throw new Error(detail);
	}

	return response.json();
};

export const getRAGFlowStatus = (token: string) => request<RAGFlowStatus>(token, '/status');

export const getKnowledgeSpaces = (token: string) => request<KnowledgeSpace[]>(token, '/spaces');

export const createKnowledgeSpace = (
	token: string,
	payload: { name: string; description?: string }
) => request<KnowledgeSpace>(token, '/spaces', { method: 'POST', body: JSON.stringify(payload) });

export const updateKnowledgeSpace = (
	token: string,
	spaceId: string,
	payload: { name?: string; description?: string }
) =>
	request<KnowledgeSpace>(token, `/spaces/${encodeURIComponent(spaceId)}`, {
		method: 'PUT',
		body: JSON.stringify(payload)
	});

export const deleteKnowledgeSpace = (token: string, spaceId: string) =>
	request(token, `/spaces/${encodeURIComponent(spaceId)}`, { method: 'DELETE' });

export const getKnowledgeSpaceMembers = (token: string, spaceId: string) =>
	request<KnowledgeSpaceMember[]>(token, `/spaces/${encodeURIComponent(spaceId)}/members`);

export const inviteKnowledgeSpaceMembers = (token: string, spaceId: string, userIds: string[]) =>
	request<{ space_id: string; invited_user_ids: string[]; existing_user_ids: string[] }>(
		token,
		`/spaces/${encodeURIComponent(spaceId)}/member-invitations`,
		{ method: 'POST', body: JSON.stringify({ user_ids: userIds }) }
	);

export const removeKnowledgeSpaceMember = (token: string, spaceId: string, userId: string) =>
	request(token, `/spaces/${encodeURIComponent(spaceId)}/members/${encodeURIComponent(userId)}`, {
		method: 'DELETE'
	});

export const getPendingKnowledgeSpaceInvitations = (token: string) =>
	request<KnowledgeSpaceInvitation[]>(token, '/space-invitations/pending');

export const respondToKnowledgeSpaceInvitation = (
	token: string,
	invitationId: string,
	accept: boolean
) =>
	request<{ accepted: boolean; space_id: string; space_name?: string }>(
		token,
		`/space-invitations/${encodeURIComponent(invitationId)}/respond`,
		{ method: 'POST', body: JSON.stringify({ accept }) }
	);

export const createKnowledgeDataset = (
	token: string,
	spaceId: string,
	payload: { name: string; chunk_method?: string }
) =>
	request<KnowledgeDataset>(token, `/spaces/${encodeURIComponent(spaceId)}/datasets`, {
		method: 'POST',
		body: JSON.stringify(payload)
	});

export const updateKnowledgeDataset = (token: string, datasetId: string, name: string) =>
	request(token, `/datasets/${encodeURIComponent(datasetId)}`, {
		method: 'PUT',
		body: JSON.stringify({ name })
	});

export const deleteKnowledgeDataset = (token: string, datasetId: string) =>
	request(token, `/datasets/${encodeURIComponent(datasetId)}`, { method: 'DELETE' });

export const getKnowledgeDocuments = (token: string, datasetId: string) =>
	request<RAGFlowDocument[]>(token, `/datasets/${encodeURIComponent(datasetId)}/documents`);

export const uploadKnowledgeDocuments = (token: string, datasetId: string, files: File[]) => {
	const form = new FormData();
	for (const file of files) form.append('files', file, safeRAGFlowFilename(file.name));
	return request<{ documents: RAGFlowDocument[]; parsing_started: string[] }>(
		token,
		`/datasets/${encodeURIComponent(datasetId)}/documents`,
		{ method: 'POST', body: form }
	);
};

export const deleteKnowledgeDocument = (token: string, datasetId: string, documentId: string) =>
	request(
		token,
		`/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}`,
		{ method: 'DELETE' }
	);

export const getKnowledgeDocumentChunks = (token: string, datasetId: string, documentId: string) =>
	request<any[]>(
		token,
		`/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/chunks`
	);

export const getKnowledgeAgents = (token: string) => request<KnowledgeAgent[]>(token, '/agents');

export type KnowledgeAgentInput = Omit<
	KnowledgeAgent,
	'id' | 'dataset_ids' | 'ragflow_chat_id' | 'created_at' | 'updated_at'
>;

export const createKnowledgeAgent = (token: string, payload: KnowledgeAgentInput) =>
	request<KnowledgeAgent>(token, '/agents', { method: 'POST', body: JSON.stringify(payload) });

export const updateKnowledgeAgent = (
	token: string,
	agentId: string,
	payload: KnowledgeAgentInput
) =>
	request<KnowledgeAgent>(token, `/agents/${encodeURIComponent(agentId)}`, {
		method: 'PUT',
		body: JSON.stringify(payload)
	});

export const deleteKnowledgeAgent = (token: string, agentId: string) =>
	request(token, `/agents/${encodeURIComponent(agentId)}`, { method: 'DELETE' });
