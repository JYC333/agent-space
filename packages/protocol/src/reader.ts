import { z } from "zod";

export const ReaderDocumentTypeSchema = z.enum(["source_item", "source_snapshot", "research_report", "research_notebook"]);
export type ReaderDocumentType = z.infer<typeof ReaderDocumentTypeSchema>;

export const ReaderDocumentRefSchema = z.object({
  document_type: ReaderDocumentTypeSchema,
  document_id: z.string().min(1),
}).strict();

export const ReaderAnnotationCreateSchema = z.object({
  document_type: ReaderDocumentTypeSchema,
  document_id: z.string().min(1),
  annotation_type: z.enum(["highlight", "comment", "excerpt", "bookmark"]),
  quote_text: z.string().min(1),
  anchor_json: z.record(z.string(), z.unknown()),
  color: z.string().optional(),
  label: z.string().optional(),
  visibility: z.enum(["private", "space_shared", "selected_users"]).optional(),
}).strict();
export type ReaderAnnotationCreate = z.infer<typeof ReaderAnnotationCreateSchema>;
