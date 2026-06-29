CREATE TABLE public.diary_entries (
    id          character varying(36)    NOT NULL DEFAULT gen_random_uuid(),
    user_id     character varying(36)    NOT NULL,
    entry_date  date                     NOT NULL,
    content     text                     NOT NULL DEFAULT '',
    created_at  timestamp with time zone NOT NULL DEFAULT now(),
    updated_at  timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT diary_entries_pkey PRIMARY KEY (id),
    CONSTRAINT diary_entries_user_date UNIQUE (user_id, entry_date),
    CONSTRAINT diary_entries_user_id_nonempty CHECK ((length(trim((user_id)::text)) > 0))
);

CREATE TABLE public.diary_reflections (
    id              character varying(36)    NOT NULL DEFAULT gen_random_uuid(),
    entry_id        character varying(36)    NOT NULL,
    reflection_date date                     NOT NULL,
    content         text                     NOT NULL,
    ai_model        character varying(64),
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT diary_reflections_pkey PRIMARY KEY (id),
    CONSTRAINT diary_reflections_entry_id_fkey FOREIGN KEY (entry_id)
        REFERENCES public.diary_entries(id) ON DELETE CASCADE
);

CREATE INDEX diary_entries_user_id_idx ON public.diary_entries USING btree (user_id);
CREATE INDEX diary_entries_date_idx ON public.diary_entries USING btree (entry_date);
CREATE INDEX diary_reflections_entry_id_idx ON public.diary_reflections USING btree (entry_id);
