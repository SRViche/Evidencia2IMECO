#lang racket

; filtrosparalelos.rkt
; Autores: Ivan Burrola, Alberto Lopez, Axel Lugo, Sebastian Viche
; Materia: Implementacion de metodos computacionales

(provide negative-parallel
         grayscale-parallel
         sepia-parallel
         edge-parallel
         gaussian-parallel
         set-num-workers!   ; permite cambiar el nº de hilos desde fuera
         get-num-workers)   ; permite leer el valor actual

;; ============================================================
;; NÚMERO DE WORKERS — parámetro mutable
;; Valor por defecto: todos los núcleos disponibles (mínimo 1).
;; Se puede cambiar en cualquier momento con set-num-workers!
;; ============================================================
(define num-workers (max 1 (processor-count)))

(define (set-num-workers! n)
  (set! num-workers (max 1 (min 64 n))))  ; clamp entre 1 y 64

(define (get-num-workers)
  num-workers)

;; ============================================================
;; UTILIDADES INTERNAS
;; ============================================================

(define (clamp v) (max 0 (min 255 v)))

;; Divide el rango [0, n) en `k` sub-rangos lo más iguales posible.
;; Retorna lista de pares (inicio . fin-exclusivo).
(define (split-range n k)
  (define chunk (quotient n k))
  (define rem   (remainder n k))
  (let loop ([i 0] [start 0] [acc '()])
    (if (= i k)
        (reverse acc)
        (let* ([extra (if (< i rem) 1 0)]
               [end   (+ start chunk extra)])
          (loop (+ i 1) end (cons (cons start end) acc))))))

;; Lanza un future por rango de píxeles y espera todos.
(define (run-parallel-pixels! n-pixels worker-fn)
  (define ranges (split-range n-pixels num-workers))
  (for-each touch
            (map (λ (range)
                   (future (λ () (worker-fn (car range) (cdr range)))))
                 ranges)))

;; Lanza un future por franja de filas (para convoluciones).
(define (run-parallel-rows! h row-fn)
  (define ranges (split-range h num-workers))
  (for-each touch
            (map (λ (range)
                   (future (λ () (row-fn (car range) (cdr range)))))
                 ranges)))

;; Acceso a canal de un byte-string por coordenadas.
(define (src-ref buf x y w c)
  (bytes-ref buf (+ (* 4 (+ x (* y w))) c)))

;; ============================================================
;; 1. NEGATIVO
;; ============================================================
(define (negative-parallel bytes-buf)
  (define out (bytes-copy bytes-buf))
  (define n   (quotient (bytes-length bytes-buf) 4))
  (run-parallel-pixels! n
    (λ (from to)
      (for ([i (in-range from to)])
        (define base (* i 4))
        (bytes-set! out (+ base 1) (- 255 (bytes-ref bytes-buf (+ base 1))))
        (bytes-set! out (+ base 2) (- 255 (bytes-ref bytes-buf (+ base 2))))
        (bytes-set! out (+ base 3) (- 255 (bytes-ref bytes-buf (+ base 3)))))))
  out)

;; ============================================================
;; 2. ESCALA DE GRISES
;; ============================================================
(define (grayscale-parallel bytes-buf)
  (define out (bytes-copy bytes-buf))
  (define n   (quotient (bytes-length bytes-buf) 4))
  (run-parallel-pixels! n
    (λ (from to)
      (for ([i (in-range from to)])
        (define base (* i 4))
        (define r (bytes-ref bytes-buf (+ base 1)))
        (define g (bytes-ref bytes-buf (+ base 2)))
        (define b (bytes-ref bytes-buf (+ base 3)))
        (define lum (exact-round (+ (* 0.299 r) (* 0.587 g) (* 0.114 b))))
        (bytes-set! out (+ base 1) lum)
        (bytes-set! out (+ base 2) lum)
        (bytes-set! out (+ base 3) lum))))
  out)

;; ============================================================
;; 3. SEPIA
;; ============================================================
(define (sepia-parallel bytes-buf)
  (define out (bytes-copy bytes-buf))
  (define n   (quotient (bytes-length bytes-buf) 4))
  (run-parallel-pixels! n
    (λ (from to)
      (for ([i (in-range from to)])
        (define base (* i 4))
        (define r (bytes-ref bytes-buf (+ base 1)))
        (define g (bytes-ref bytes-buf (+ base 2)))
        (define b (bytes-ref bytes-buf (+ base 3)))
        (bytes-set! out (+ base 1) (clamp (exact-round (+ (* 0.393 r) (* 0.769 g) (* 0.189 b)))))
        (bytes-set! out (+ base 2) (clamp (exact-round (+ (* 0.349 r) (* 0.686 g) (* 0.168 b)))))
        (bytes-set! out (+ base 3) (clamp (exact-round (+ (* 0.272 r) (* 0.534 g) (* 0.131 b))))))))
  out)

;; ============================================================
;; 4. EDGE DETECTION (Laplaciano 3x3)
;; ============================================================
(define (edge-parallel bytes-buf w h)
  (define src (bytes-copy bytes-buf))
  (define out (make-bytes (bytes-length bytes-buf) 0))
  ;; Copiar canal alpha
  (for ([i (in-range (* w h))])
    (bytes-set! out (* i 4) (bytes-ref src (* i 4))))
  (run-parallel-rows! h
    (λ (row-from row-to)
      (for* ([y (in-range (max 1 row-from) (min (- h 1) row-to))]
             [x (in-range 1 (- w 1))])
        (define base (* 4 (+ x (* y w))))
        (for ([c (in-range 1 4)])
          (define val
            (+ (*  8 (src-ref src x y w c))
               (* -1 (src-ref src (- x 1) (- y 1) w c))
               (* -1 (src-ref src x       (- y 1) w c))
               (* -1 (src-ref src (+ x 1) (- y 1) w c))
               (* -1 (src-ref src (- x 1) y       w c))
               (* -1 (src-ref src (+ x 1) y       w c))
               (* -1 (src-ref src (- x 1) (+ y 1) w c))
               (* -1 (src-ref src x       (+ y 1) w c))
               (* -1 (src-ref src (+ x 1) (+ y 1) w c))))
          (bytes-set! out (+ base c) (clamp val))))))
  out)

;; ============================================================
;; 5. GAUSSIAN BLUR (Kernel 3x3)
;; ============================================================
(define (gaussian-parallel bytes-buf w h)
  (define src (bytes-copy bytes-buf))
  (define out (bytes-copy bytes-buf))
  (run-parallel-rows! h
    (λ (row-from row-to)
      (for* ([y (in-range (max 1 row-from) (min (- h 1) row-to))]
             [x (in-range 1 (- w 1))])
        (define base (* 4 (+ x (* y w))))
        (for ([c (in-range 1 4)])
          (define val
            (+ (* 4 (src-ref src x       y       w c))
               (* 2 (src-ref src x       (- y 1) w c))
               (* 2 (src-ref src x       (+ y 1) w c))
               (* 2 (src-ref src (- x 1) y       w c))
               (* 2 (src-ref src (+ x 1) y       w c))
               (* 1 (src-ref src (- x 1) (- y 1) w c))
               (* 1 (src-ref src (+ x 1) (- y 1) w c))
               (* 1 (src-ref src (- x 1) (+ y 1) w c))
               (* 1 (src-ref src (+ x 1) (+ y 1) w c))))
          (bytes-set! out (+ base c) (quotient val 16))))))
  out)
