export { RetrievalProjectionService, objectRefKey } from "./projectionService";
export { RetrievalSearchService } from "./searchService";
export type { RetrievalSearchServiceOptions } from "./searchService";
export {
  RetrievalFeedbackService,
  DEFAULT_RETRIEVAL_FEEDBACK,
  feedbackBoostMultiplier,
  retrievalFeedbackQueryHash,
} from "./feedback";
export type {
  FeedbackEventRow,
  RetrievalFeedbackBoostInput,
  RetrievalFeedbackConfig,
  RetrievalFeedbackRecordInput,
} from "./feedback";
export { RetrievalEmbeddingStore, toVectorLiteral } from "./embeddingStore";
export type { PendingChunk } from "./embeddingStore";
export {
  applyRerank,
  rerankWindowSize,
  DEFAULT_RERANK_CONFIG,
} from "./reranker";
export type {
  Reranker,
  RerankCandidate,
  RerankConfig,
  RerankScore,
} from "./reranker";
export { mergeRewriteVariants, MAX_REWRITE_VARIANTS } from "./queryRewrite";
export type { QueryRewriter } from "./queryRewrite";
export {
  assembleBrief,
  buildBriefCandidates,
  DEFAULT_SYNTHESIS_CONFIG,
} from "./synthesis";
export {
  buildRetrievalBriefArtifactSpec,
  persistRetrievalBriefArtifact,
  RETRIEVAL_BRIEF_ARTIFACT_TYPE,
} from "./briefArtifacts";
export type {
  RetrievalBriefArtifactContext,
  RetrievalBriefArtifactSpec,
} from "./briefArtifacts";
export type {
  BriefCandidate,
  SynthesisConfig,
  SynthesisResult,
  Synthesizer,
} from "./synthesis";
export { classifyIntent, rankingConfigForIntent } from "./intent";
export type { RetrievalIntent } from "./intent";
export { parseRelationalIntent } from "./relationalIntent";
export type { RelationalIntent, RelationalIntentKind } from "./relationalIntent";
export {
  RetrievalMaintenanceService,
  DEFAULT_MAINTENANCE_CONFIG,
} from "./maintenance";
export {
  createRetrievalMaintenanceProposalPacket,
  persistRetrievalMaintenanceReportArtifact,
  registerRetrievalMaintenanceProposalAppliers,
  RETRIEVAL_MAINTENANCE_PACKET_PROPOSAL_TYPE,
  RETRIEVAL_MAINTENANCE_REPORT_ARTIFACT_TYPE,
} from "./maintenanceArtifacts";
export type { RetrievalMaintenanceReportContext } from "./maintenanceArtifacts";
export {
  buildRetrievalEvalReportArtifactSpec,
  persistRetrievalEvalReportArtifact,
  RETRIEVAL_EVAL_REPORT_ARTIFACT_TYPE,
} from "./evalArtifacts";
export {
  persistRetrievalCalibrationDecisionArtifact,
  RETRIEVAL_CALIBRATION_DECISION_ARTIFACT_TYPE,
  RetrievalCalibrationDecisionError,
} from "./calibrationArtifacts";
export {
  buildRetrievalEvalDiagnosticsReport,
  buildRetrievalEvalDiagnosticsReportFromArtifactMetadata,
  buildRetrievalEvalDiagnosticsReportFromMetadata,
} from "./evalDiagnostics";
export {
  createRetrievalDiagnosticsProposalPacket,
  registerRetrievalDiagnosticsProposalAppliers,
  RETRIEVAL_DIAGNOSTICS_PACKET_PROPOSAL_TYPE,
} from "./diagnosticsArtifacts";
export {
  persistRetrievalExplainReportArtifact,
  RETRIEVAL_EXPLAIN_REPORT_ARTIFACT_TYPE,
} from "./explainArtifacts";
export type {
  RetrievalEvalReportArtifactContext,
  RetrievalEvalReportArtifactSpec,
} from "./evalArtifacts";
export type {
  MaintenanceConfig,
  MaintenanceFinding,
  MaintenanceFindingKind,
  MaintenanceObjectRef,
  MaintenanceReport,
} from "./maintenance";
export { RetrievalRegistry } from "./registry";
export type { RetrievalDomainAdapter } from "./registry";
export {
  normalizeAlias,
  normalizeSlugCandidate,
  normalizeTextForSearch,
  stripMarkdownForSearch,
  tokenizeSimple,
  excerptAroundQuery,
} from "./normalize";
export { extractRetrievalLinks } from "./linkExtractor";
export type { ExtractedRetrievalLink } from "./linkExtractor";
export {
  loadSourceConnectionIdsForTargets,
  loadSourcePolicySnapshots,
  loadViewerSpaceRole,
  sourceConnectionIdsFromJson,
  sourceConnectionIdsFromMetadata,
  sourceConnectionIdsFromSourceRefs,
  sourceEgressPoliciesForSnapshots,
  sourcePolicyAllowsRead,
} from "./sourcePolicy";
export type { SourcePolicySnapshot, SourceReadContext } from "./sourcePolicy";
export * from "./types";
