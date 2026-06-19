CREATE TABLE public.dairy_entries (
    id          character varying(36)    NOT NULL DEFAULT gen_random_uuid(),
    user_id     character varying(36)    NOT NULL,
    entry_date  date                     NOT NULL,
    content     text                     NOT NULL DEFAULT '',
    created_at  timestamp with time zone NOT NULL DEFAULT now(),
    updated_at  timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT dairy_entries_pkey PRIMARY KEY (id),
    CONSTRAINT dairy_entries_user_date UNIQUE (user_id, entry_date),
    CONSTRAINT dairy_entries_user_id_nonempty CHECK ((length(trim((user_id)::text)) > 0))
);

CREATE TABLE public.dairy_reflections (
    id              character varying(36)    NOT NULL DEFAULT gen_random_uuid(),
    entry_id        character varying(36)    NOT NULL,
    reflection_date date                     NOT NULL,
    content         text                     NOT NULL,
    ai_model        character varying(64),
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT dairy_reflections_pkey PRIMARY KEY (id),
    CONSTRAINT dairy_reflections_entry_id_fkey FOREIGN KEY (entry_id)
        REFERENCES public.dairy_entries(id) ON DELETE CASCADE
);

CREATE INDEX dairy_entries_user_id_idx ON public.dairy_entries USING btree (user_id);
CREATE INDEX dairy_entries_date_idx ON public.dairy_entries USING btree (entry_date);
CREATE INDEX dairy_reflections_entry_id_idx ON public.dairy_reflections USING btree (entry_id);
