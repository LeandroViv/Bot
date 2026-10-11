def generar_respuesta_y_partitura_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    historial_contexto = extraer_partitura_historica()
    
    system_prompt = (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo. "
        "Tenés a tu disposición el historial de notas de voz del usuario para aprender sus métricas rítmicas:\n"
        f"{historial_contexto}\n\n"
        "REGLA DE SÍNTESIS DE VOZ:\n"
        "Generá una respuesta en texto y construí una partitura métrica detallada palabra por palabra. "
        "Deduce la duración (duracion_ms entre 100 y 350) y la intensidad (intensidad_db entre -2.5 y 1.5) "
        "de cada palabra analizando su sílaba tónica y el tono de la charla.\n\n"
        "Devolvé OBLIGATORIAMENTE un JSON estricto con esta estructura exacta, sin texto extra fuera:\n"
        "{\n"
        "  \"texto_completo\": \"Tu respuesta hablada aquí\",\n"
        "  \"partitura\": [\n"
        "    {\"palabra\": \"Che,\", \"duracion_ms\": 120, \"intensidad_db\": -1.0},\n"
        "    {\"palabra\": \"escuchá\", \"duracion_ms\": 250, \"intensidad_db\": 0.0}\n"
        "  ]\n"
        "}"
    )
    
    respuesta_raw = ""
    # Intentamos con Gemini si no está bloqueado
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            res = client.models.generate_content(
                model="gemini-2.5-flash",  # Usamos una versión estable y liviana
                contents=f"Mensaje del oyente: \"{prompt_usuario}\"",
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json"
                )
            )
            if res and res.text:
                respuesta_raw = res.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
                print("⚠️ [CUOTA EXCEDIDA]: Gemini bloqueado, saltando automáticamente a Llama local (Ollama)...")
            else:
                print(f"⚠️ Error en Gemini partitura: {e}")

    # Si Gemini falló o está bloqueado por cuota, usamos Ollama (Llama 3.2 local)
    if not respuesta_raw or GEMINI_BLOQUEADO_POR_CUOTA:
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt + "\nRespondé ÚNICAMENTE en JSON válido sin markdown extra."},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.7},
            "stream": False,
        }
        try:
            res_local = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=20)
            if res_local.status_code == 200:
                respuesta_raw = res_local.json().get("message", {}).get("content", "").strip()
                # Limpiamos bloques de código si Llama los llega a agregar por capricho
                respuesta_raw = re.sub(r'^```json\s*', '', respuesta_raw)
                respuesta_raw = re.sub(r'^```\s*', '', respuesta_raw)
                respuesta_raw = re.sub(r'\s*```$', '', respuesta_raw).strip()
        except Exception as ex_local:
            print(f"⚠️ Error conectando con Llama local: {ex_local}")

    try:
        datos = json_lib.loads(respuesta_raw)
        texto = datos.get("texto_completo", "Che, todo bien por acá.")
        partitura = datos.get("partitura", [])
        if not partitura:
            raise ValueError("Partitura vacía")
        return texto, partitura
    except Exception:
        texto_fallback = "Che, se me cruzaron los cables un segundo, decime de nuevo."
        partitura_fallback = [
            {"palabra": "Che,", "duracion_ms": 120, "intensidad_db": -1.0},
            {"palabra": "todo", "duracion_ms": 150, "intensidad_db": 0.0},
            {"palabra": "bien.", "duracion_ms": 250, "intensidad_db": -1.5}
        ]
        return texto_fallback, partitura_fallback


def sintetizar_con_partitura_de_ia(texto, partitura, ogg_salida="resp.ogg"):
    wav_temp_timbre = "temp_timbre_bark.wav"
    wav_temp_final = "temp_dinamica_final.wav"
    sample_rate = 24000

    timbre_ok = False
    if BARK_DISPONIBLE:
        try:
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            device = "cpu"
            model = model.to(device)

            inputs = processor(f"[es] {texto[:200]}", voice_preset="v2/es_speaker_2").to(device)
            with torch.no_grad():
                # CORREGIDO: Eliminamos el argumento duplicado max_new_tokens para evitar el crash de transformers
                audio_bark = model.generate(**inputs)
            
            audio_bark = audio_bark.cpu().numpy().squeeze()
            if len(audio_bark) > 5000:
                sf.write(wav_temp_timbre, audio_bark, sample_rate)
                timbre_ok = os.path.exists(wav_temp_timbre)
        except Exception as e:
            print(f"⚠️ Error en timbre Bark: {e}")

    if not timbre_ok:
        print("⚠️ [FALLBACK TIMBRE]: Usando tono base seguro.")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=180:duration=3", wav_temp_timbre], check=True)

    try:
        data_timbre, sr = sf.read(wav_temp_timbre)
        if len(data_timbre.shape) > 1:
            data_timbre = np.mean(data_timbre, axis=1)

        max_val = np.max(np.abs(data_timbre))
        if max_val > 0:
            data_timbre = data_timbre / max_val

        if len(data_timbre) < sr * 1.0:
            data_timbre = np.tile(data_timbre, 2)

        audio_dinamico = np.array([], dtype=np.float32)
        chunk_base_size = int(sr * 0.15)

        if not partitura:
            partitura = [{"palabra": w, "duracion_ms": 180, "intensidad_db": 0.0} for w in texto.split()]

        for item in partitura:
            duracion_ms = item.get("duracion_ms", 180)
            intensidad_db = item.get("intensidad_db", 0.0)

            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            if muestras_bloque <= 0:
                muestras_bloque = chunk_base_size

            start_idx = np.random.randint(0, max(1, len(data_timbre) - muestras_bloque))
            fragmento = data_timbre[start_idx : start_idx + muestras_bloque]

            intensidad_db_segura = max(min(intensidad_db, 1.5), -2.5)
            mult_vol = 10 ** (intensidad_db_segura / 20.0)
            
            audio_dinamico = np.concatenate((audio_dinamico, fragmento * mult_vol))

        if len(audio_dinamico) < sr * 1.0:
            audio_dinamico = data_timbre

        sf.write(wav_temp_final, audio_dinamico, sr)
    except Exception as e:
        print(f"⚠️ Error aplicando partitura segura, usando respaldo: {e}")
        subprocess.run(["cp", wav_temp_timbre, wav_temp_final], check=True)

    filtros = [
        "highpass=f=80",
        "lowpass=f=7500",
        "dynaudnorm=f=150:g=15:p=0.9",
        "volume=1.2"
    ]

    subprocess.run([
        "ffmpeg", "-y", "-i", wav_temp_final,
        "-filter:a", ",".join(filtros),
        "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
        ogg_salida
    ], check=True)

    for temp_f in [wav_temp_timbre, wav_temp_final]:
        if os.path.exists(temp_f):
            os.remove(temp_f)
