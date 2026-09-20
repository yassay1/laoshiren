export interface Thing {
  id: string;
  user_id?: string;
  name: string;
  status: string;
  current_stage?: string;
  deadline_at?: string | null;
  merged_into_thing_id?: string | null;
  version: number;
  created_at?: string;
  updated_at?: string;
}
