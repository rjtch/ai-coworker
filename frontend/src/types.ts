export type Role = "user" | "assistant" | "system";

export type ChatAttachment = {
  name: string;
  mime_type: string;
  data: string;
};

export type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  attachments?: ChatAttachment[];
  agent?: string | null;
  intent?: string | null;
  streaming?: boolean;
};

export function uid(): string {
  return crypto.randomUUID();
}

export const ACCEPTED_FILE_TYPES = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";

export function mimeFromFile(file: File): string {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".pdf")) return "application/pdf";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  return file.type || "application/octet-stream";
}

export async function fileToAttachment(file: File): Promise<ChatAttachment> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]!);
  }
  return {
    name: file.name,
    mime_type: mimeFromFile(file),
    data: btoa(binary),
  };
}
