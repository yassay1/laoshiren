export interface Task {
  id: string;
  user_id?: string;
  thing_id?: string | null;
  title: string;
  status: string;
  due_at?: string | null;
  version: number;
  completed_at?: string | null;
  recurrence_interval_days?: number | null;
  created_at?: string;
  updated_at?: string;
}
