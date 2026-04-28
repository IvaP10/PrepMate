-- InterAI Database Schema for Supabase
-- Adapted from existing schema to work with Supabase auth

-- ── User Info (profiles) ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT,
  full_name TEXT,
  avatar_url TEXT,
  resume_text TEXT,
  resume_json JSONB DEFAULT '{}'::jsonb,
  profile_json JSONB DEFAULT '{}'::jsonb,
  external_profile_signals JSONB DEFAULT '{}'::jsonb,
  profile_completed BOOLEAN DEFAULT FALSE,
  target_role TEXT DEFAULT 'Software Engineer',
  goal_focus TEXT DEFAULT 'Nail the technical rounds',
  mock_interview_count INTEGER DEFAULT 0,
  practice_interview_count INTEGER DEFAULT 0,
  interviews_remaining INTEGER DEFAULT 1,
  is_unlimited BOOLEAN DEFAULT FALSE,
  plan_type TEXT DEFAULT 'free',
  resume_uploaded_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_select_own" ON public.profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "profiles_insert_own" ON public.profiles FOR INSERT WITH CHECK (auth.uid() = id);
CREATE POLICY "profiles_update_own" ON public.profiles FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "profiles_delete_own" ON public.profiles FOR DELETE USING (auth.uid() = id);


-- ── Resumes ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.resumes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  file_url TEXT,
  file_name TEXT,
  parsed_data JSONB DEFAULT '{}'::jsonb,
  missing_keywords TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.resumes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "resumes_select_own" ON public.resumes FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "resumes_insert_own" ON public.resumes FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "resumes_update_own" ON public.resumes FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "resumes_delete_own" ON public.resumes FOR DELETE USING (auth.uid() = user_id);


-- ── Interviews ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.interviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  interview_mode TEXT NOT NULL CHECK (interview_mode IN ('practice', 'mock')),
  interview_type TEXT NOT NULL,
  job_title TEXT,
  strictness_level TEXT DEFAULT 'medium' CHECK (strictness_level IN ('easy', 'medium', 'hard')),
  status TEXT DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed', 'cancelled')),
  overall_score NUMERIC(5,2),
  feedback_summary TEXT,
  report_json JSONB DEFAULT '{}'::jsonb,
  freeze_time NUMERIC(5,2) DEFAULT 0,
  conciseness_score INTEGER CHECK (conciseness_score >= 0 AND conciseness_score <= 100),
  filler_words INTEGER DEFAULT 0,
  speaking_pace INTEGER DEFAULT 0,
  questions_data JSONB DEFAULT '[]'::jsonb,
  responses_data JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

ALTER TABLE public.interviews ENABLE ROW LEVEL SECURITY;

CREATE POLICY "interviews_select_own" ON public.interviews FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "interviews_insert_own" ON public.interviews FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "interviews_update_own" ON public.interviews FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "interviews_delete_own" ON public.interviews FOR DELETE USING (auth.uid() = user_id);


-- ── Analytics (performance trends) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.analytics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  performance_score INTEGER CHECK (performance_score >= 0 AND performance_score <= 100),
  technical_skills INTEGER CHECK (technical_skills >= 0 AND technical_skills <= 100),
  communication INTEGER CHECK (communication >= 0 AND communication <= 100),
  problem_solving INTEGER CHECK (problem_solving >= 0 AND problem_solving <= 100),
  confidence INTEGER CHECK (confidence >= 0 AND confidence <= 100),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.analytics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_select_own" ON public.analytics FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "analytics_insert_own" ON public.analytics FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "analytics_update_own" ON public.analytics FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "analytics_delete_own" ON public.analytics FOR DELETE USING (auth.uid() = user_id);


-- ── Settings (user preferences) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID UNIQUE NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  difficulty TEXT DEFAULT 'medium' CHECK (difficulty IN ('easy', 'medium', 'hard')),
  ai_persona TEXT DEFAULT 'professional' CHECK (ai_persona IN ('professional', 'friendly', 'challenging')),
  notifications_enabled BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "settings_select_own" ON public.settings FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "settings_insert_own" ON public.settings FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "settings_update_own" ON public.settings FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "settings_delete_own" ON public.settings FOR DELETE USING (auth.uid() = user_id);
