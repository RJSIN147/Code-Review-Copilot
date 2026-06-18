import { useState, useCallback } from "react";
import { Layout } from "./components/Layout";
import { AnalyzeForm } from "./components/AnalyzeForm";
import { TaskList } from "./components/TaskList";
import { TaskStatusCard } from "./components/TaskStatusCard";
import { SummaryMetrics } from "./components/SummaryMetrics";
import { ResultsPanel } from "./components/ResultsPanel";

function App() {
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>(undefined);

  const handleSelectTask = useCallback((id: string) => {
    setSelectedTaskId(id);
  }, []);

  const handleAnalyzeSuccess = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
  }, []);

  return (
    <Layout>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[55%_45%]">
        {/* Left column: submit form and task list */}
        <div className="flex flex-col gap-6">
          <AnalyzeForm onSuccess={handleAnalyzeSuccess} />
          <TaskList selectedTaskId={selectedTaskId} onSelectTask={handleSelectTask} />
        </div>

        {/* Right column: selected task details */}
        <div className="flex flex-col gap-6">
          <TaskStatusCard taskId={selectedTaskId ?? ""} />
          <SummaryMetrics taskId={selectedTaskId ?? ""} />
          <ResultsPanel taskId={selectedTaskId ?? ""} />
        </div>
      </div>
    </Layout>
  );
}

export default App;
