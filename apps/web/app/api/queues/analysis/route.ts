import { handleCallback } from "@vercel/queue";
import {
  processCloudStage,
  type StageMessage,
} from "../../../../lib/cloud-analysis";
export const maxDuration = 300;
export const POST = handleCallback<StageMessage>(
  async (message) => {
    try {
      await processCloudStage(message);
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "analysis_stage_retry",
          job_id: message?.id,
          stage: message?.stage,
          type: error instanceof Error ? error.constructor.name : "unknown",
        }),
      );
      throw error;
    }
  },
  { visibilityTimeoutSeconds: 300, retry: () => ({ afterSeconds: 30 }) },
);
